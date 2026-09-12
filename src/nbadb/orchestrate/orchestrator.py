from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

import duckdb
import polars as pl
from loguru import logger

from nbadb.core.config import NbaDbSettings, get_settings
from nbadb.core.db import DBManager
from nbadb.core.errors import ExtractionError, ParserInputCaptureIntegrityError
from nbadb.core.types import SeasonType, season_type_upstream_unavailable_reason
from nbadb.extract.bronze import (
    LogicalCallReceiptBinding,
    canonical_parameters_payload,
    canonical_parameters_sha256,
)
from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
from nbadb.extract.registry import (
    EndpointRegistry,
    EndpointRegistryAuthority,
    EndpointRegistryAuthorityError,
)
from nbadb.extract.registry import (
    registry as _global_registry,
)
from nbadb.load.multi import create_multi_loader
from nbadb.orchestrate.capture_session import (
    CaptureSessionState,
    IncompleteCaptureIdentity,
    PrivateCaptureSession,
    PrivateGenerationIdentity,
)
from nbadb.orchestrate.cume_workload_contract import (
    CumeWorkloadContractError,
    CumeWorkloadDisposition,
    CumeWorkloadValue,
)
from nbadb.orchestrate.discovery import (
    DiscoveryCaptureCompletion,
    EntityDiscovery,
    GameDiscoveryResult,
    PlayerIdDiscoveryResult,
    PlayerTeamSeasonDiscoveryResult,
)
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope, DiscoveryArtifactStore
from nbadb.orchestrate.execution_policy import endpoint_family
from nbadb.orchestrate.extraction_contract import (
    DISCOVERY_SEED_ENDPOINT_PATTERNS,
    DISCOVERY_SEED_OWNED_ENDPOINTS,
)
from nbadb.orchestrate.extraction_progress import ExtractionProgressStore
from nbadb.orchestrate.extractor_runner import (
    ChunkPersistenceAdmissionsV1,
    ChunkPersistenceCallbackV1,
    ExtractorRunner,
    PatternExtractionResult,
    PendingRequestObservation,
    RequestClosureExecutionAuthority,
)
from nbadb.orchestrate.init_coverage import InitDiscoveryCoverageError
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.live_snapshot import (
    LiveSnapshotExtraction,
    LiveSnapshotWarehouse,
    LiveSourceCallResult,
)
from nbadb.orchestrate.persistence import atomic_write_text
from nbadb.orchestrate.planning import (
    CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT,
    ExtractionPlanItem,
    build_extraction_plan,
    cume_workload_execution_params,
    executable_endpoint_routes,
    resolve_video_context_measures,
)
from nbadb.orchestrate.request_closure_production import (
    ProductionRequestClosureBuild,
    ReceiptOnlyCaptureFactory,
    StaticRequestClosureAuthorityV1,
    build_ordinary_request_closure_authority,
)
from nbadb.orchestrate.request_closure_runtime import RequestObservation
from nbadb.orchestrate.request_closure_staging import (
    IncompleteRequestClosureEvidence,
    RequestClosureObservationInventory,
    RequestClosureScopeGap,
    bind_or_classify_committed_request_observation,
)
from nbadb.orchestrate.seasons import (
    current_season,
    recent_seasons,
    season_range,
    season_string,
)
from nbadb.orchestrate.staging_batches import (
    SourceScopeReplacementAttestation,
    StagingBatchStore,
    StagingChunkMetadata,
    StagingFrameBatch,
    digest_jsonable,
    frame_content_hash,
    frame_schema_hash,
)
from nbadb.orchestrate.staging_map import (
    CONDITIONAL_STAGING_KEYS,
    STAGING_MAP,
    StagingEntry,
    get_by_endpoint,
)
from nbadb.orchestrate.successor_execution_plan import (
    SealedUpdateExecutionDispatch,
    SuccessorExecutionPlan,
)
from nbadb.orchestrate.successor_execution_restore import (
    logical_bindings_from_replacement_attestations,
    successor_receipts_from_replacement_attestations,
)
from nbadb.orchestrate.successor_transform_authority import (
    TransformOutputAttestation,
    build_successor_transform_attestations,
)
from nbadb.orchestrate.successor_update_contract import (
    ObservedDeltaReceipt,
    SuccessorGenerationBuild,
    SuccessorGenerationState,
    SuccessorUpdateContractError,
    SuccessorUpdateMode,
    SuccessorUpdateTransaction,
)
from nbadb.orchestrate.transformers import (
    discover_all_transformers,
    expected_transform_output_tables,
    require_complete_transformer_universe,
)
from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore
from nbadb.schemas.registry import get_input_schema
from nbadb.transform.pipeline import TransformPipeline
from nbadb.transform.quality import DataQualityMonitor
from nbadb.transform.schema_version import schema_hash_for_frame

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from concurrent.futures import ThreadPoolExecutor

    from nbadb.contracts.logical_provider_parameter_binding import (
        LogicalProviderParameterBindingV1,
    )
    from nbadb.extract.raw_request_capture import RawRequestCaptureSnapshotV2
    from nbadb.orchestrate.live_snapshot import (
        LivePlanAuthorityBindingFactory,
        RawRequestCaptureContextFactory,
    )
    from nbadb.orchestrate.raw_request_assurance import RawRequestAssuranceAuthorityV2
    from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
    from nbadb.orchestrate.raw_request_manifest import RawRequestAuthorityManifestV2
    from nbadb.orchestrate.raw_request_store import (
        RawRequestAuthorityPersistenceReceiptV2,
        RawRequestManifestAuthorityV2,
    )
    from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1
    from nbadb.orchestrate.w2_source_call_preparation import (
        W2SourceCallPreparationRuntime,
    )

DEFAULT_SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)
type LoadMode = Literal["replace", "append"]


def _classified_upstream_unavailable_pairs(
    pairs: set[tuple[str, str]] | frozenset[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    unavailable: dict[tuple[str, str], str] = {}
    for pair in pairs:
        season, season_type = pair
        try:
            season_start_year = int(season[:4])
            reason = season_type_upstream_unavailable_reason(season_start_year, season_type)
        except (TypeError, ValueError):
            continue
        if reason is not None:
            unavailable[pair] = reason
    return unavailable


def _apply_player_shard(player_ids: list[int]) -> list[int]:
    raw_index = os.environ.get("NBADB_PLAYER_SHARD_INDEX", "").strip()
    raw_count = os.environ.get("NBADB_PLAYER_SHARD_COUNT", "").strip()
    if not raw_index and not raw_count:
        return player_ids
    if not raw_index or not raw_count:
        msg = "NBADB_PLAYER_SHARD_INDEX and NBADB_PLAYER_SHARD_COUNT must both be set"
        raise ValueError(msg)

    shard_index = int(raw_index)
    shard_count = int(raw_count)
    if shard_count < 1:
        msg = "NBADB_PLAYER_SHARD_COUNT must be >= 1"
        raise ValueError(msg)
    if shard_index < 0 or shard_index >= shard_count:
        msg = "NBADB_PLAYER_SHARD_INDEX must be >= 0 and < NBADB_PLAYER_SHARD_COUNT"
        raise ValueError(msg)
    if shard_count == 1:
        return player_ids

    return [
        player_id
        for offset, player_id in enumerate(player_ids)
        if offset % shard_count == shard_index
    ]


def _source_logical_provider_parameter_authority(
    source_result: dict[str, object],
) -> tuple[LogicalProviderParameterBindingV1 | None, str | None]:
    """Return the exact precompiled pair carried by one source-result DTO."""

    from nbadb.contracts.logical_provider_parameter_binding import (
        LogicalProviderParameterBindingV1,
    )

    binding_key = "logical_provider_parameter_binding"
    pin_key = "expected_logical_provider_parameter_binding_sha256"
    binding_present = binding_key in source_result
    pin_present = pin_key in source_result
    if binding_present != pin_present:
        raise ParserInputCaptureIntegrityError(
            "raw-request logical/provider parameter binding is one-sided"
        )
    if not binding_present:
        return None, None
    parameter_binding = source_result[binding_key]
    expected_parameter_binding_sha256 = source_result[pin_key]
    if (
        type(parameter_binding) is not LogicalProviderParameterBindingV1
        or type(expected_parameter_binding_sha256) is not str
    ):
        raise ParserInputCaptureIntegrityError(
            "raw-request logical/provider parameter binding has a foreign shape"
        )
    return parameter_binding, cast("str | None", expected_parameter_binding_sha256)


def _require_requested_endpoint_routes(
    requested_endpoints: set[str],
    *,
    requested_patterns: set[str] | None = None,
    discovery_backed_endpoints: frozenset[str] = frozenset(),
) -> None:
    routes = executable_endpoint_routes()
    missing: list[str] = []
    for endpoint_name in sorted(requested_endpoints):
        if endpoint_name in discovery_backed_endpoints:
            endpoint_patterns = set(DISCOVERY_SEED_ENDPOINT_PATTERNS.get(endpoint_name, ()))
        else:
            endpoint_patterns = {
                pattern for endpoint, pattern in routes if endpoint == endpoint_name
            }
        unsupported_patterns = sorted((requested_patterns or set()) - endpoint_patterns)
        if not endpoint_patterns:
            missing.append(endpoint_name)
        elif unsupported_patterns:
            missing.append(f"{endpoint_name} ({', '.join(unsupported_patterns)})")
    if missing:
        raise ExtractionError(
            "Backfill planning has no executable route for requested endpoint(s): "
            + ", ".join(missing)
        )


def _with_cume_foundations(endpoints: list[str] | None) -> list[str] | None:
    """Expand an explicit endpoint scope with mandatory cume foundations."""

    if endpoints is None:
        return None
    expanded = list(dict.fromkeys(endpoints))
    for endpoint in tuple(expanded):
        foundation = CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT.get(endpoint)
        if foundation is not None and foundation not in expanded:
            expanded.append(foundation)
    return expanded


def _filter_backfill_plan(
    plan: list[ExtractionPlanItem],
    *,
    endpoints: list[str] | None,
    patterns: list[str] | None,
) -> list[ExtractionPlanItem]:
    """Apply a backfill scope without allowing dependent cume bypass."""

    if not endpoints and not patterns:
        return plan
    endpoint_set = set(endpoints) if endpoints else None
    pattern_set = set(patterns) if patterns else None
    filtered: list[ExtractionPlanItem] = []
    for item in plan:
        if pattern_set and item.pattern not in pattern_set:
            continue
        if endpoint_set is None:
            filtered.append(item)
            continue

        dependency = item.cume_dependency
        if dependency is not None:
            foundation_requested = any(
                entry.endpoint_name in endpoint_set for entry in item.entries
            )
            dependent_requested = dependency.dependent_entries[0].endpoint_name in endpoint_set
            if dependent_requested:
                filtered.append(item)
            elif foundation_requested:
                filtered.append(
                    ExtractionPlanItem(
                        label=item.label,
                        pattern=item.pattern,
                        entries=list(item.entries),
                        params=item.params,
                        priority=item.priority,
                    )
                )
            continue

        matching_entries = [entry for entry in item.entries if entry.endpoint_name in endpoint_set]
        if matching_entries:
            filtered.append(
                ExtractionPlanItem(
                    label=item.label,
                    pattern=item.pattern,
                    entries=matching_entries,
                    params=item.params,
                    priority=item.priority,
                )
            )
    return filtered


def _derive_cume_workloads(
    item: ExtractionPlanItem,
    source_results: list[dict[str, object]],
    *,
    capture_required: bool,
) -> list[CumeWorkloadValue]:
    """Derive dependent workloads from exact successful foundation calls."""

    dependency = item.cume_dependency
    if dependency is None:
        raise CumeWorkloadContractError("cume workload derivation requires a dependency plan")
    foundation_entry = item.entries[0]
    expected_foundation = CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT[
        dependency.dependent_entries[0].endpoint_name
    ]
    if foundation_entry.endpoint_name != expected_foundation:
        raise CumeWorkloadContractError("cume foundation endpoint does not match its dependent")

    planned_by_json = {json.dumps(params, sort_keys=True): params for params in item.params}
    if len(planned_by_json) != len(item.params):
        raise CumeWorkloadContractError("cume foundation plan contains duplicate parameter scopes")

    source_by_json: dict[str, dict[str, object]] = {}
    for source_result in source_results:
        source_endpoint = source_result.get("source_endpoint_name")
        source_params_json = source_result.get("source_params_json")
        if source_endpoint != foundation_entry.endpoint_name:
            raise CumeWorkloadContractError("cume foundation source endpoint identity mismatch")
        if not isinstance(source_params_json, str) or source_params_json not in planned_by_json:
            raise CumeWorkloadContractError(
                "cume foundation returned an unexpected parameter scope"
            )
        try:
            parsed_params = json.loads(source_params_json)
        except json.JSONDecodeError as exc:
            raise CumeWorkloadContractError(
                "cume foundation source parameters are not valid JSON"
            ) from exc
        planned_params = planned_by_json[source_params_json]
        if (
            not isinstance(parsed_params, dict)
            or parsed_params != planned_params
            or source_params_json != json.dumps(parsed_params, sort_keys=True)
        ):
            raise CumeWorkloadContractError(
                "cume foundation source parameters are not canonical or scope-exact"
            )
        if source_params_json in source_by_json:
            raise CumeWorkloadContractError("cume foundation returned duplicate source evidence")
        source_by_json[source_params_json] = source_result

    if set(source_by_json) != set(planned_by_json):
        raise CumeWorkloadContractError(
            "cume foundation evidence is incomplete for the planned parameter scopes"
        )

    schema = get_input_schema(foundation_entry.staging_key)
    if schema is None:
        raise CumeWorkloadContractError("cume foundation staging schema is missing")
    expected_route = (
        f"{foundation_entry.endpoint_name}:"
        f"{foundation_entry.staging_key}:{foundation_entry.result_set_index}"
    )
    workloads: list[CumeWorkloadValue] = []
    entity_key = f"{dependency.entity_kind.value}_id"
    for source_params_json, planned_params in planned_by_json.items():
        source_result = source_by_json[source_params_json]
        frames = source_result.get("frames")
        if not isinstance(frames, dict) or set(frames) != {foundation_entry.staging_key}:
            raise CumeWorkloadContractError(
                "cume foundation must expose exactly its source-call staging frame"
            )
        source_frames = cast("dict[str, object]", frames)
        frame = source_frames[foundation_entry.staging_key]
        if not isinstance(frame, pl.DataFrame):
            raise CumeWorkloadContractError("cume foundation staging frame has an invalid type")
        expected_keys = source_result.get("expected_staging_keys")
        normalized_expected_keys = (
            tuple(expected_keys) if isinstance(expected_keys, list | tuple) else ()
        )
        if normalized_expected_keys != (foundation_entry.staging_key,):
            raise CumeWorkloadContractError(
                "cume foundation expected-staging-key evidence is invalid"
            )
        try:
            schema.validate(frame)
        except Exception as exc:
            raise CumeWorkloadContractError(
                "cume foundation frame failed its staging schema"
            ) from exc

        receipt_binding = source_result.get("receipt_binding")
        if receipt_binding is not None and not isinstance(
            receipt_binding, LogicalCallReceiptBinding
        ):
            raise CumeWorkloadContractError("cume foundation receipt binding is invalid")
        if capture_required and receipt_binding is None:
            raise CumeWorkloadContractError(
                "capture-required cume foundation lacks a logical-call receipt"
            )
        foundation_receipt_sha256: str | None = None
        provider_authority_sha256: str | None = None
        if receipt_binding is not None:
            if (
                receipt_binding.endpoint_name != foundation_entry.endpoint_name
                or receipt_binding.logical_parameters_sha256
                != canonical_parameters_sha256(planned_params)
                or receipt_binding.result_route_ids != (expected_route,)
                or source_result.get("result_route_ids_by_staging_key")
                != ((foundation_entry.staging_key, expected_route),)
            ):
                raise CumeWorkloadContractError(
                    "cume foundation receipt does not bind the exact source scope and route"
                )
            foundation_receipt_sha256 = receipt_binding.logical_call_receipt_sha256
            provider_authority_sha256 = receipt_binding.provider_authority_sha256

        game_ids = frame.get_column("game_id").to_list()
        entity_id = planned_params.get(entity_key)
        season = planned_params.get("season")
        season_type = planned_params.get("season_type")
        if (
            type(entity_id) is not int
            or not isinstance(season, str)
            or not isinstance(season_type, str)
        ):
            raise CumeWorkloadContractError("cume foundation planned scope is malformed")
        if game_ids:
            workload = CumeWorkloadValue.complete(
                entity_kind=dependency.entity_kind,
                entity_id=entity_id,
                season=season,
                season_type=season_type,
                game_ids=game_ids,
                foundation_receipt_sha256=foundation_receipt_sha256,
                provider_authority_sha256=provider_authority_sha256,
            )
        else:
            workload = CumeWorkloadValue.typed_zero(
                entity_kind=dependency.entity_kind,
                entity_id=entity_id,
                season=season,
                season_type=season_type,
                reason_code="foundation_success_empty",
                foundation_receipt_sha256=foundation_receipt_sha256,
                provider_authority_sha256=provider_authority_sha256,
            )
        workloads.append(workload)
    return workloads


def _combine_pattern_results(
    first: PatternExtractionResult,
    second: PatternExtractionResult,
) -> PatternExtractionResult:
    """Combine sequential foundation/dependent accounting into one plan slice."""

    frames = dict(first.frames)
    overlap = set(frames) & set(second.frames)
    if overlap:
        raise CumeWorkloadContractError(
            f"cume foundation and dependent staging frames overlap: {sorted(overlap)!r}"
        )
    frames.update(second.frames)
    circuits = dict(first.response_contract_circuit)
    circuits.update(second.response_contract_circuit)
    return PatternExtractionResult(
        frames=frames,
        eligible_calls=first.eligible_calls + second.eligible_calls,
        support_skip_count=first.support_skip_count + second.support_skip_count,
        journal_skip_count=first.journal_skip_count + second.journal_skip_count,
        retry_skip_count=first.retry_skip_count + second.retry_skip_count,
        success_count=first.success_count + second.success_count,
        failure_count=first.failure_count + second.failure_count,
        deferred_failure_count=(first.deferred_failure_count + second.deferred_failure_count),
        row_count=first.row_count + second.row_count,
        scheduled_calls=first.scheduled_calls + second.scheduled_calls,
        unattempted_eligible_calls=(
            first.unattempted_eligible_calls + second.unattempted_eligible_calls
        ),
        errors=[*first.errors, *second.errors],
        response_contract_circuit=circuits,
    )


def _group_exact_pairs(
    pairs: set[tuple[str, str]] | frozenset[tuple[str, str]],
    *,
    seasons: list[str],
    season_types: list[str],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """Group seasons with identical required season types without widening pairs."""
    seasons_by_types: dict[tuple[str, ...], list[str]] = {}
    for season in dict.fromkeys(seasons):
        exact_types = tuple(
            season_type
            for season_type in dict.fromkeys(season_types)
            if (season, season_type) in pairs
        )
        if exact_types:
            seasons_by_types.setdefault(exact_types, []).append(season)
    return tuple(
        (tuple(grouped_seasons), exact_types)
        for exact_types, grouped_seasons in seasons_by_types.items()
    )


@dataclass
class PipelineResult:
    """Outcome of a pipeline run."""

    tables_updated: int = 0
    rows_total: int = 0
    duration_seconds: float = 0.0
    failed_extractions: int = 0
    failed_loads: int = 0
    skipped_extractions: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    """Raw extraction output plus current-run recovery signals."""

    raw: dict[str, pl.DataFrame]
    pattern_failures: int = 0
    failed_calls: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SuccessorExecutionOutcome:
    """Complete exact-plan result retained before private capture sealing."""

    result: PipelineResult
    delta_receipts: tuple[ObservedDeltaReceipt, ...]
    transform_output_attestations: tuple[TransformOutputAttestation, ...]
    planned_route_replacement_bindings_sha256: str


def _validate_successor_execution_authority(
    transaction: SuccessorUpdateTransaction,
    plan: SuccessorExecutionPlan,
) -> None:
    """Reconcile a sealed UPDATE projection with its immutable transaction."""

    if not isinstance(plan, SuccessorExecutionPlan):
        raise TypeError("plan must be a SuccessorExecutionPlan")
    projected_scopes = tuple(
        sorted(
            (scope for dispatch in plan.dispatches for scope in dispatch.requested_scopes),
            key=lambda scope: scope.identity_sha256,
        )
    )
    mismatches: list[str] = []
    if plan.identity_sha256 != transaction.intent.successor_execution_plan_sha256:
        mismatches.append("successor_execution_plan_sha256")
    if plan.baseline_identity_sha256 != transaction.baseline.identity_sha256:
        mismatches.append("baseline_identity_sha256")
    if plan.requested_route_scopes_sha256 != transaction.intent.requested_scopes_sha256:
        mismatches.append("requested_route_scopes_sha256")
    if (
        plan.planned_route_replacement_bindings_sha256
        != transaction.intent.planned_route_replacement_bindings_sha256
    ):
        mismatches.append("planned_route_replacement_bindings_sha256")
    if projected_scopes != transaction.intent.requested_scopes:
        mismatches.append("requested_scopes")
    if mismatches:
        raise SuccessorUpdateContractError(
            "successor execution plan differs from its immutable transaction: "
            + ", ".join(mismatches)
        )


def _entries_for_successor_authority(
    transaction: SuccessorUpdateTransaction,
    dispatch: SealedUpdateExecutionDispatch,
) -> tuple[StagingEntry, ...]:
    """Resolve one sealed dispatch to exact ordered current staging entries."""

    from nbadb.contracts.staging_route_contract import staging_route_contract_bundle

    routes = staging_route_contract_bundle().by_route_id
    entries_by_route: dict[str, StagingEntry] = {}
    for entry in STAGING_MAP:
        route_id = f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
        if route_id in entries_by_route:
            raise SuccessorUpdateContractError(
                "current staging map contains duplicate result-route identities"
            )
        entries_by_route[route_id] = entry

    ordered_entries: list[StagingEntry] = []
    for position, (route_id, scope) in enumerate(
        zip(dispatch.staging_route_ids, dispatch.requested_scopes, strict=True)
    ):
        route = routes.get(route_id)
        entry = entries_by_route.get(route_id)
        if route is None or entry is None:
            raise SuccessorUpdateContractError(
                f"sealed dispatch route {position} is absent from current staging authority"
            )
        if (
            scope.route_id != route_id
            or scope.endpoint_name != dispatch.endpoint_name
            or scope.parameters != dispatch.parameters
            or scope.scope_sha256 != dispatch.parameters_sha256
            or scope.route_contract_sha256 != route.contract_sha256
            or route.endpoint_name != dispatch.endpoint_name
            or route.param_pattern != dispatch.pattern
            or route.provider_authority_sha256 != transaction.baseline.provider_authority_sha256
            or entry.endpoint_name != route.endpoint_name
            or entry.staging_key != route.staging_key
            or entry.result_set_index != route.declared_result_set_index
            or entry.param_pattern != route.param_pattern
        ):
            raise SuccessorUpdateContractError(
                f"sealed dispatch route {position} differs from current route authority"
            )
        ordered_entries.append(entry)
    return tuple(ordered_entries)


def validate_successor_runtime_plan(
    transaction: SuccessorUpdateTransaction,
    plan: SuccessorExecutionPlan,
) -> tuple[tuple[StagingEntry, ...], ...]:
    """Pure pre-admission validation of every exact sealed UPDATE call."""

    logical_call_keys = [
        (dispatch.endpoint_name, dispatch.parameters_sha256) for dispatch in plan.dispatches
    ]
    if len(logical_call_keys) != len(set(logical_call_keys)):
        raise SuccessorUpdateContractError(
            "successor runtime plan dispatches a logical provider call more than once"
        )
    _validate_successor_execution_authority(transaction, plan)
    support_date = datetime.fromisoformat(
        transaction.intent.as_of_utc.replace("Z", "+00:00")
    ).date()
    resolved: list[tuple[StagingEntry, ...]] = []
    for dispatch in plan.dispatches:
        entries = _entries_for_successor_authority(transaction, dispatch)
        unsupported_routes = tuple(
            dispatch.staging_route_ids[index]
            for index, entry in enumerate(entries)
            if not ExtractorRunner._entry_is_supported(
                entry,
                dispatch.parameters,
                today=support_date,
            )
        )
        if unsupported_routes:
            raise SuccessorUpdateContractError(
                "sealed-plan route is filtered by intent.as_of_utc: " + ",".join(unsupported_routes)
            )
        _multi, single_entries, multi_by_endpoint = ExtractorRunner._classify_entries(list(entries))
        if len(single_entries) + len(multi_by_endpoint) != 1:
            raise SuccessorUpdateContractError(
                "one sealed dispatch must classify as exactly one logical provider call"
            )
        resolved.append(entries)
    return tuple(resolved)


class _ProgressReporter(Protocol):
    """Minimal progress surface used by the orchestrator stack."""

    def start_phase(self, name: str, total: int = 0) -> None: ...

    def update_phase_info(self, info: str) -> None: ...

    def complete_phase(self) -> None: ...

    def log_discovery(self, entity: str, count: int) -> None: ...

    def start_pattern(self, pattern: str, total: int) -> None: ...

    def advance_pattern(self, *, success: bool = True, rows: int = 0) -> None: ...

    def record_skip(self, n: int = 1) -> None: ...

    def log_resume_context(self, done: int, failed: int, rows: int) -> None: ...

    def update_rate_info(self, current_rate: float, base_rate: float) -> None: ...

    def update_circuit_breakers(self, tripped: list[str]) -> None: ...

    def export_summary(self) -> object: ...


class _BoundLogger(Protocol):
    def info(self, message: str, *args: object) -> None: ...

    def warning(self, message: str, *args: object) -> None: ...

    def error(self, message: str, *args: object) -> None: ...


class _DiscoveryService(Protocol):
    async def discover_game_ids_result(
        self,
        seasons: list[str],
        on_progress: _ProgressReporter | None = None,
        season_types: list[str] | None = None,
    ) -> GameDiscoveryResult: ...

    async def discover_game_dates(self, game_log_df: pl.DataFrame) -> list[str]: ...

    async def discover_player_ids(self, season: str | None = None) -> list[int]: ...

    async def discover_all_player_ids(self, season: str | None = None) -> list[int]: ...

    async def discover_all_player_ids_result(
        self,
        season: str | None = None,
    ) -> PlayerIdDiscoveryResult: ...

    async def discover_team_ids(self) -> list[int]: ...

    async def discover_current_team_ids(self) -> list[int]: ...

    async def discover_player_team_season_params_result(
        self,
        seasons: list[str],
        season_types: list[str] | None = None,
    ) -> PlayerTeamSeasonDiscoveryResult: ...


class Orchestrator:
    """Main orchestration engine.

    Coordinates extraction, transformation, and loading across
    all pipeline run modes (init, daily, monthly, retry).

    Resume logic is handled automatically via the extraction
    journal -- each call checks ``journal.was_extracted()``
    before invoking an endpoint.
    """

    def __init__(
        self,
        settings: NbaDbSettings | None = None,
        progress: _ProgressReporter | None = None,
        *,
        capture_session: PrivateCaptureSession | None = None,
        successor_transaction: SuccessorUpdateTransaction | None = None,
        successor_registry: EndpointRegistry | None = None,
        successor_registry_authority: EndpointRegistryAuthority | None = None,
        successor_transform_scratch_parent: Path | None = None,
        expected_successor_transform_scratch_identity: tuple[int, int] | None = None,
        successor_transform_scratch_max_bytes: int | None = None,
        raw_request_execution_identity: RawRequestExecutionIdentityV1 | None = None,
        raw_request_assurance_authority: RawRequestAssuranceAuthorityV2 | None = None,
        raw_request_manifest_authority: RawRequestManifestAuthorityV2 | None = None,
        w2_preparation_runtime: W2SourceCallPreparationRuntime | None = None,
        live_raw_request_capture_context_factory: RawRequestCaptureContextFactory | None = None,
        live_plan_authority_binding_factory: LivePlanAuthorityBindingFactory | None = None,
    ) -> None:
        if capture_session is not None:
            if not isinstance(capture_session, PrivateCaptureSession):
                raise TypeError("capture_session must be a PrivateCaptureSession")
            if capture_session.closed or capture_session.state is not CaptureSessionState.ADMITTED:
                raise ParserInputCaptureIntegrityError(
                    "injected private capture session must already be admitted and open"
                )
        if successor_transaction is not None:
            if not isinstance(successor_transaction, SuccessorUpdateTransaction):
                raise TypeError("successor_transaction must be a SuccessorUpdateTransaction")
            if successor_transaction.state is not SuccessorGenerationState.CANDIDATE:
                raise SuccessorUpdateContractError(
                    "successor extraction requires an exact candidate transaction"
                )
            if capture_session is None:
                raise SuccessorUpdateContractError(
                    "successor extraction requires an admitted private capture session"
                )
        if raw_request_execution_identity is not None:
            # Keep this import behind construction: staging-contract discovery imports
            # the orchestrate package while it is still initializing.
            from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1

            if type(raw_request_execution_identity) is not RawRequestExecutionIdentityV1:
                raise TypeError(
                    "raw_request_execution_identity must be a RawRequestExecutionIdentityV1"
                )
        if raw_request_manifest_authority is not None:
            from nbadb.orchestrate.raw_request_store import RawRequestManifestAuthorityV2

            if type(raw_request_manifest_authority) is not RawRequestManifestAuthorityV2:
                raise TypeError(
                    "raw_request_manifest_authority must be a RawRequestManifestAuthorityV2"
                )
        if raw_request_assurance_authority is not None:
            from nbadb.orchestrate.raw_request_assurance import (
                RawRequestAssuranceAuthorityV2,
            )

            if type(raw_request_assurance_authority) is not RawRequestAssuranceAuthorityV2:
                raise TypeError(
                    "raw_request_assurance_authority must be a RawRequestAssuranceAuthorityV2"
                )
        if raw_request_execution_identity is None and (
            raw_request_assurance_authority is not None
            or raw_request_manifest_authority is not None
        ):
            raise ParserInputCaptureIntegrityError(
                "raw-request capture cannot admit authorities without an execution identity"
            )
        if w2_preparation_runtime is not None:
            from nbadb.orchestrate.w2_source_call_preparation import (
                W2SourceCallPreparationRuntime,
            )

            if type(w2_preparation_runtime) is not W2SourceCallPreparationRuntime:
                raise TypeError("w2_preparation_runtime must be a W2SourceCallPreparationRuntime")
            if raw_request_execution_identity is None:
                raise ParserInputCaptureIntegrityError(
                    "W2 preparation cannot be admitted without a raw-request execution identity"
                )
        live_authority_factories = (
            live_raw_request_capture_context_factory,
            live_plan_authority_binding_factory,
        )
        if any(item is None for item in live_authority_factories) and any(
            item is not None for item in live_authority_factories
        ):
            raise ParserInputCaptureIntegrityError(
                "live Raw V2 context and sealed-plan authority factories must be supplied together"
            )
        if any(item is not None and not callable(item) for item in live_authority_factories):
            raise TypeError("live authority factories must be callable")
        if live_raw_request_capture_context_factory is not None and (
            raw_request_execution_identity is None or w2_preparation_runtime is None
        ):
            raise ParserInputCaptureIntegrityError(
                "live authority factories require Raw Authority V2 and W2 execution resources"
            )
        if raw_request_execution_identity is not None:
            if raw_request_assurance_authority is None:
                raise ParserInputCaptureIntegrityError(
                    "raw-request capture requires a verified assurance authority"
                )
            if raw_request_assurance_authority.source_sha != (
                raw_request_execution_identity.source_sha
            ):
                raise ParserInputCaptureIntegrityError(
                    "raw-request assurance authority differs from execution identity"
                )
            if raw_request_manifest_authority is not None and (
                raw_request_manifest_authority.source_sha,
                raw_request_manifest_authority.run_id,
                raw_request_manifest_authority.run_attempt,
                raw_request_manifest_authority.chain_id,
                raw_request_manifest_authority.lane_id,
            ) != (
                raw_request_execution_identity.source_sha,
                raw_request_execution_identity.run_id,
                raw_request_execution_identity.run_attempt,
                raw_request_execution_identity.chain_id,
                raw_request_execution_identity.lane_id,
            ):
                raise ParserInputCaptureIntegrityError(
                    "raw-request manifest authority differs from execution identity"
                )
            if raw_request_manifest_authority is not None and (
                raw_request_manifest_authority.field_authority_sha256,
                raw_request_manifest_authority.model_authority_sha256,
            ) != (
                raw_request_assurance_authority.field_authority_sha256,
                raw_request_assurance_authority.model_authority_sha256,
            ):
                raise ParserInputCaptureIntegrityError(
                    "raw-request manifest authority differs from assurance authority"
                )
        self._settings: NbaDbSettings = settings if settings is not None else get_settings()
        self._db: DBManager | None = None
        self._journal: PipelineJournal | None = None
        self._progress: _ProgressReporter | None = progress
        self._capture_session = capture_session
        self._capture_identity: PrivateGenerationIdentity | IncompleteCaptureIdentity | None = None
        self._successor_transaction = successor_transaction
        self._successor_registry = successor_registry
        self._successor_registry_authority = successor_registry_authority
        self._successor_transform_scratch_parent = successor_transform_scratch_parent
        self._expected_successor_transform_scratch_identity = (
            expected_successor_transform_scratch_identity
        )
        self._successor_transform_scratch_max_bytes = successor_transform_scratch_max_bytes
        self._successor_delta_receipts: dict[str, ObservedDeltaReceipt] = {}
        self._transform_output_attestations: tuple[TransformOutputAttestation, ...] = ()
        self._active_successor_dispatch: SealedUpdateExecutionDispatch | None = None
        self._successor_execution_plan: SuccessorExecutionPlan | None = None
        self._staging_batch_store: StagingBatchStore | None = None
        self._staging_batch_store_connection: object | None = None
        self._request_closure_observations: dict[str, RequestObservation] = {}
        self._request_closure_incomplete: dict[str, IncompleteRequestClosureEvidence] = {}
        self._request_closure_inventory: RequestClosureObservationInventory | None = None
        self._receipt_only_capture_factory: ReceiptOnlyCaptureFactory | None = None
        self._raw_request_execution_identity = raw_request_execution_identity
        self._raw_request_assurance_authority = raw_request_assurance_authority
        self._raw_request_manifest_authority = raw_request_manifest_authority
        self._w2_preparation_runtime = w2_preparation_runtime
        self._live_raw_request_capture_context_factory = live_raw_request_capture_context_factory
        self._live_plan_authority_binding_factory = live_plan_authority_binding_factory
        self._raw_request_authority_manifest: RawRequestAuthorityManifestV2 | None = None
        self._raw_request_persistence_receipts: dict[
            str,
            RawRequestAuthorityPersistenceReceiptV2,
        ] = {}

    # ── lifecycle helpers ──────────────────────────────────────

    def _init_db(self) -> tuple[DBManager, PipelineJournal]:
        """Ensure DB + journal are ready, re-using if already init'd.

        Completed entries are preserved so resume stays idempotent, while any
        lingering in-progress rows from a prior process are made replayable.
        This recovery assumes a single active writer per pipeline DB/journal.
        """
        if self._db is not None and self._journal is not None:
            return self._db, self._journal

        if self._successor_transaction is not None and self._successor_execution_plan is None:
            raise SuccessorUpdateContractError(
                "successor database recovery requires a validated execution plan"
            )

        db = DBManager(
            sqlite_path=self._settings.sqlite_path,
            duckdb_path=self._settings.duckdb_path,
        )
        db.init()
        journal = PipelineJournal(
            db.duckdb,
            successor_generation_sha256=(
                self._successor_transaction.generation_identity_sha256
                if self._successor_transaction is not None
                else None
            ),
        )
        journal.recover_interrupted_running()

        if self._successor_transaction is not None:
            self._restore_successor_execution_state(journal)

        self._db = db
        self._journal = journal
        return db, journal

    def _restore_successor_execution_state(self, journal: PipelineJournal) -> None:
        """Reconstruct durable route receipts and private roots after a crash."""

        session = self._capture_session
        if session is None:
            raise SuccessorUpdateContractError(
                "successor recovery requires an admitted private capture session"
            )
        attestations = journal.load_successor_replacement_attestations()
        if not attestations:
            return
        self._record_successor_replacements(attestations)
        session.restore_completed_bindings(
            logical_bindings_from_replacement_attestations(attestations)
        )

    def _successor_dispatch_already_complete(
        self,
        dispatch: SealedUpdateExecutionDispatch,
    ) -> bool:
        """Return True when restored receipts already close this sealed dispatch.

        A partial route inventory fails closed so resume cannot re-provider
        completed members or adopt an incomplete logical root.
        """

        expected_scope_ids = tuple(scope.identity_sha256 for scope in dispatch.requested_scopes)
        receipts = tuple(
            self._successor_delta_receipts[scope_id]
            for scope_id in expected_scope_ids
            if scope_id in self._successor_delta_receipts
        )
        if not receipts:
            return False
        observed_scope_ids = tuple(receipt.requested_scope_sha256 for receipt in receipts)
        observed_routes = tuple(
            scope.route_id
            for scope in dispatch.requested_scopes
            if scope.identity_sha256 in self._successor_delta_receipts
        )
        logical_roots = {receipt.logical_call_receipt_sha256 for receipt in receipts}
        dispatch_ids = {receipt.execution_dispatch_identity_sha256 for receipt in receipts}
        if (
            observed_scope_ids != expected_scope_ids
            or set(observed_routes) != set(dispatch.staging_route_ids)
            or len(observed_routes) != len(dispatch.staging_route_ids)
            or len(set(observed_routes)) != len(observed_routes)
            or len(logical_roots) != 1
            or dispatch_ids != {dispatch.identity_sha256}
        ):
            raise SuccessorUpdateContractError(
                "durable successor replacements do not exactly cover one execution dispatch"
            )
        return True

    def _require_successor_registry_authority(
        self,
        *,
        endpoint_name: str | None = None,
    ) -> EndpointRegistry:
        registry = self._successor_registry
        authority = self._successor_registry_authority
        if not isinstance(registry, EndpointRegistry) or not isinstance(
            authority, EndpointRegistryAuthority
        ):
            raise SuccessorUpdateContractError(
                "successor execution requires an admitted endpoint registry authority"
            )
        try:
            authority.require_current(
                registry,
                required_endpoint_name=endpoint_name,
            )
        except EndpointRegistryAuthorityError as exc:
            raise SuccessorUpdateContractError(
                "successor endpoint registry authority differs"
            ) from exc
        return registry

    def _require_successor_transform_scratch_authority(
        self,
    ) -> tuple[Path, tuple[int, int], int]:
        scratch_parent = self._successor_transform_scratch_parent
        identity = self._expected_successor_transform_scratch_identity
        maximum_bytes = self._successor_transform_scratch_max_bytes
        if (
            not isinstance(scratch_parent, Path)
            or not scratch_parent.is_absolute()
            or scratch_parent.resolve(strict=False) != scratch_parent
            or type(identity) is not tuple
            or len(identity) != 2
            or any(type(value) is not int or value < 0 for value in identity)
            or identity[1] == 0
            or type(maximum_bytes) is not int
            or maximum_bytes <= 0
            or maximum_bytes > (1 << 63) - 1
        ):
            raise SuccessorUpdateContractError("successor transform scratch authority is invalid")
        return scratch_parent, identity, maximum_bytes

    def _build_runner(self, journal: PipelineJournal) -> ExtractorRunner:
        if self._successor_transaction is None:
            _global_registry.discover()
            active_registry = _global_registry
        else:
            active_registry = self._require_successor_registry_authority()
        capture_factory = None
        call_admission = None
        conditional_route_admission = None
        if self._capture_session is not None:
            self._require_capture_session_admitted()
            capture_factory = self._capture_session.contract_for
        elif self._receipt_only_capture_factory is not None:
            capture_factory = self._receipt_only_capture_factory.contract_for
        if self._successor_transaction is not None:
            call_admission = self._admit_successor_provider_call
            conditional_route_admission = self._admit_successor_conditional_result_routes
        return ExtractorRunner(
            registry=active_registry,
            settings=self._settings,
            journal=journal,
            rate_limit=self._settings.rate_limit,
            progress=self._progress,
            capture_contract_factory=capture_factory,
            call_admission=call_admission,
            conditional_route_admission=conditional_route_admission,
        )

    def _enable_ordinary_request_closure_capture(self) -> None:
        """Enable bounded receipt-only capture when no private session was injected."""

        if self._successor_transaction is not None:
            return
        self._receipt_only_capture_factory = (
            None
            if self._capture_session is not None
            else ReceiptOnlyCaptureFactory(
                execution_identity=self._raw_request_execution_identity,
            )
        )

    @staticmethod
    def _build_ordinary_request_closure(
        runner: ExtractorRunner,
        plan: list[ExtractionPlanItem],
        *,
        run_mode: Literal["init", "daily", "monthly", "backfill"],
        support_date: date,
        discovery_seed_requested: bool,
        recurring_live_requested: bool,
    ) -> ProductionRequestClosureBuild:
        # Run-mode unit tests use lightweight runner doubles that intentionally do
        # not expose provider/capture internals.  Production always supplies the
        # concrete runner built above, so keep assurance strict on the real path
        # without asking unrelated orchestration tests to forge closure evidence.
        if not isinstance(runner, ExtractorRunner):
            return ProductionRequestClosureBuild(None, (), support_date)
        return build_ordinary_request_closure_authority(
            plan,
            registry=runner._registry,
            run_mode=run_mode,
            support_date=support_date,
            discovery_seed_requested=discovery_seed_requested,
            recurring_live_requested=recurring_live_requested,
        )

    def _build_discovery(
        self,
        thread_pool: ThreadPoolExecutor | None = None,
        *,
        run_mode: str,
    ) -> EntityDiscovery:
        """Create an EntityDiscovery wired to the global registry."""
        capture_factory = None
        capture_completion_sink = None
        call_admission = None
        if self._capture_session is not None:
            self._require_capture_session_admitted()
            capture_factory = self._capture_session.contract_for

            def _persist_completion(completion: DiscoveryCaptureCompletion) -> None:
                self._persist_discovery_capture_completion(completion, run_mode=run_mode)

            capture_completion_sink = _persist_completion
        if self._successor_transaction is not None:
            call_admission = self._admit_successor_provider_call
            active_registry = self._require_successor_registry_authority()
        else:
            active_registry = _global_registry
        return EntityDiscovery(
            active_registry,
            thread_pool=thread_pool,
            settings=self._settings,
            capture_contract_factory=capture_factory,
            capture_completion_sink=capture_completion_sink,
            call_admission=call_admission,
        )

    @property
    def capture_identity(self) -> PrivateGenerationIdentity | IncompleteCaptureIdentity | None:
        """Return the path-free terminal identity for the injected capture session."""

        return self._capture_identity

    @property
    def successor_delta_receipts(self) -> tuple[ObservedDeltaReceipt, ...]:
        """Return the exact generation-bound route receipts accumulated so far."""

        return tuple(
            self._successor_delta_receipts[key] for key in sorted(self._successor_delta_receipts)
        )

    @property
    def planned_route_replacement_bindings_sha256(self) -> str:
        """Return the exact sealed-plan binding authority for this execution."""

        plan = self._successor_execution_plan
        if plan is None:
            raise SuccessorUpdateContractError(
                "successor planned route authority is unavailable before plan validation"
            )
        return plan.planned_route_replacement_bindings_sha256

    @property
    def transform_output_attestations(self) -> tuple[TransformOutputAttestation, ...]:
        """Return the last fully loaded deterministic transform inventory."""

        return self._transform_output_attestations

    @property
    def request_closure_inventory(self) -> RequestClosureObservationInventory | None:
        """Return the last post-commit request-closure join, when enabled."""

        return self._request_closure_inventory

    @property
    def raw_request_persistence_receipts(
        self,
    ) -> tuple[RawRequestAuthorityPersistenceReceiptV2, ...]:
        """Return replay-independent raw-authority persistence receipts."""

        return tuple(
            self._raw_request_persistence_receipts[key]
            for key in sorted(self._raw_request_persistence_receipts)
        )

    @property
    def raw_request_authority_manifest(self) -> RawRequestAuthorityManifestV2 | None:
        """Return the latest strict raw-authority generation sealed in DuckDB."""

        return self._raw_request_authority_manifest

    def _require_raw_request_manifest_authority(
        self,
        request_closure_authority: RequestClosureExecutionAuthority | None,
        static_authorities: tuple[StaticRequestClosureAuthorityV1, ...] = (),
    ) -> RawRequestManifestAuthorityV2:
        """Recompile and verify the exact runtime authority before any write."""

        execution = self._raw_request_execution_identity
        assurance_authority = self._raw_request_assurance_authority
        manifest_authority = self._raw_request_manifest_authority
        if execution is None or assurance_authority is None:
            raise ParserInputCaptureIntegrityError(
                "raw-request capture lacks its verified execution/assurance authority"
            )
        if request_closure_authority is None and not static_authorities:
            raise ParserInputCaptureIntegrityError(
                "raw-request capture lacks an exact request-closure authority"
            )
        if (
            type(static_authorities) is not tuple
            or any(type(item) is not StaticRequestClosureAuthorityV1 for item in static_authorities)
            or static_authorities
            != tuple(sorted(static_authorities, key=lambda item: item.endpoint_name))
            or len({item.endpoint_name for item in static_authorities}) != len(static_authorities)
        ):
            raise ParserInputCaptureIntegrityError(
                "raw-request capture has invalid static request authorities"
            )
        from nbadb.orchestrate.raw_request_store import (
            RawRequestAuthorityPersistenceError,
            compile_raw_request_manifest_authority,
        )

        try:
            recomputed = compile_raw_request_manifest_authority(
                execution,
                request_closure_authority,
                static_authorities=static_authorities,
                assurance_authority=assurance_authority,
            )
        except RawRequestAuthorityPersistenceError as exc:
            raise ParserInputCaptureIntegrityError(
                "raw-request manifest authority could not be recomputed"
            ) from exc
        if manifest_authority is None:
            self._raw_request_manifest_authority = recomputed
            return recomputed
        if recomputed != manifest_authority:
            raise ParserInputCaptureIntegrityError(
                "raw-request manifest authority differs from request closure"
            )
        return manifest_authority

    def _record_raw_request_persistence_receipt(
        self,
        receipt: RawRequestAuthorityPersistenceReceiptV2,
    ) -> None:
        """Retain one semantic persistence receipt across idempotent replays."""

        from nbadb.orchestrate.raw_request_store import (
            RawRequestAuthorityPersistenceReceiptV2,
        )

        if type(receipt) is not RawRequestAuthorityPersistenceReceiptV2:
            raise ParserInputCaptureIntegrityError(
                "raw-request persistence returned an invalid receipt"
            )
        prior = self._raw_request_persistence_receipts.get(receipt.bundle_sha256)
        if prior is not None and prior.receipt_sha256 != receipt.receipt_sha256:
            raise ParserInputCaptureIntegrityError(
                "raw-request persistence receipt changed during replay"
            )
        if prior is None:
            self._raw_request_persistence_receipts[receipt.bundle_sha256] = receipt

    def _require_successor_mode(self, expected: SuccessorUpdateMode) -> None:
        transaction = self._successor_transaction
        if transaction is None:
            raise SuccessorUpdateContractError(
                f"{expected.value} execution requires an immutable successor candidate "
                "transaction and admitted private capture session"
            )
        if transaction.intent.mode is not expected:
            raise SuccessorUpdateContractError(
                f"{expected.value} execution does not match the successor update intent"
            )

    def _reject_later_derived_successor_fanout(self, *, surface: str) -> None:
        """Fail closed before discovery, live, or pattern fan-out on successor."""

        if self._successor_transaction is None:
            return
        raise SuccessorUpdateContractError(
            f"{surface} refuses later-derived or out-of-manifest fan-out; "
            "ordinary and live provider dispatches must come from the sealed update manifest"
        )

    def _require_complete_successor_receipts(self) -> None:
        transaction = self._successor_transaction
        if transaction is None:
            return
        expected = {scope.identity_sha256 for scope in transaction.intent.requested_scopes}
        observed = set(self._successor_delta_receipts)
        if expected != observed:
            missing = sorted(expected - observed)
            unexpected = sorted(observed - expected)
            details: list[str] = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if unexpected:
                details.append("unexpected=" + ",".join(unexpected))
            raise SuccessorUpdateContractError(
                "successor route replacement receipts are incomplete: " + "; ".join(details)
            )
        build = SuccessorGenerationBuild(
            baseline_identity_sha256=transaction.baseline.identity_sha256,
            update_intent_sha256=transaction.intent.identity_sha256,
            source_sha=transaction.intent.source_sha,
            observed_delta_receipts=self.successor_delta_receipts,
        )
        if (
            build.planned_route_replacement_bindings_sha256
            != transaction.intent.planned_route_replacement_bindings_sha256
            or build.planned_route_replacement_bindings_sha256
            != self.planned_route_replacement_bindings_sha256
        ):
            raise SuccessorUpdateContractError(
                "successor replacement receipts differ from the sealed execution plan"
            )

    def _require_capture_session_admitted(self) -> None:
        session = self._capture_session
        if session is None:
            return
        if session.closed or session.state is not CaptureSessionState.ADMITTED:
            raise ParserInputCaptureIntegrityError(
                "private capture session is not open in admitted state"
            )

    @staticmethod
    def _capture_result_is_complete(result: PipelineResult) -> bool:
        return not result.failed_extractions and not result.failed_loads and not result.errors

    def _close_capture_session(
        self,
    ) -> PrivateGenerationIdentity | IncompleteCaptureIdentity | None:
        if self._capture_identity is not None or self._capture_session is None:
            return self._capture_identity
        self._capture_identity = self._capture_session.close()
        return self._capture_identity

    def _seal_capture_session(self) -> PrivateGenerationIdentity | None:
        if self._capture_session is None:
            return None
        self._require_capture_session_admitted()
        identity = self._capture_session.seal()
        closed_identity = self._capture_session.close()
        if closed_identity is not identity:
            raise ParserInputCaptureIntegrityError(
                "sealed capture identity changed while releasing its writer lock"
            )
        self._capture_identity = identity
        return identity

    async def _run_capture_managed(
        self,
        operation: Callable[[], Awaitable[PipelineResult]],
    ) -> PipelineResult:
        if self._capture_session is None:
            return await operation()
        try:
            self._require_capture_session_admitted()
            result = await operation()
            if self._capture_result_is_complete(result):
                self._require_complete_successor_receipts()
                self._seal_capture_session()
            else:
                self._close_capture_session()
            return result
        except BaseException:
            self._close_capture_session()
            raise

    def _validate_successor_execution_plan(self, plan: SuccessorExecutionPlan) -> None:
        transaction = self._successor_transaction
        if transaction is None:
            raise SuccessorUpdateContractError(
                "exact-plan execution requires an immutable successor transaction"
            )
        _validate_successor_execution_authority(transaction, plan)

    def _entries_for_successor_dispatch(
        self,
        dispatch: SealedUpdateExecutionDispatch,
    ) -> list[StagingEntry]:
        """Resolve the exact ordered plan routes to their current staging entries."""

        transaction = self._successor_transaction
        if transaction is None:
            raise SuccessorUpdateContractError(
                "sealed dispatch resolution requires a successor transaction"
            )
        return list(_entries_for_successor_authority(transaction, dispatch))

    def _checkpoint_and_close_successor_database(self) -> None:
        """Durably checkpoint public databases without closing admitted capture."""

        db = self._db
        if db is None:
            return
        try:
            db.duckdb.execute("CHECKPOINT")
        finally:
            try:
                db.close()
            finally:
                self._db = None
                self._journal = None
                self._staging_batch_store = None
                self._staging_batch_store_connection = None

    def _export_successor_staging_resources(
        self,
        db: DBManager,
        *,
        staging_keys: tuple[str, ...],
    ) -> None:
        """Refresh every changed staging table in SQLite, CSV, and Parquet.

        The candidate DuckDB is already the durable staging authority.  The
        full-publication contract also exposes every canonical static staging
        table and any admitted response-conditional table through the three
        secondary formats, so exact successor execution must replace those
        resources before terminal assurance.
        """

        from nbadb.core.types import validate_sql_identifier
        from nbadb.load.csv_loader import CSVLoader
        from nbadb.load.parquet_loader import ParquetLoader
        from nbadb.load.sqlite import SQLiteLoader

        if self._successor_transaction is None:
            raise SuccessorUpdateContractError(
                "staging publication refresh requires an immutable successor transaction"
            )
        expected_formats = {"sqlite", "duckdb", "csv", "parquet"}
        if set(self._settings.formats) != expected_formats:
            raise SuccessorUpdateContractError(
                "exact successor staging refresh requires all four publication formats"
            )
        sqlite_path = self._settings.sqlite_path
        if sqlite_path is None:
            raise SuccessorUpdateContractError(
                "exact successor staging refresh requires a SQLite destination"
            )
        canonical_keys = {entry.staging_key for entry in STAGING_MAP} | set(
            CONDITIONAL_STAGING_KEYS
        )
        normalized_keys = tuple(sorted(set(staging_keys)))
        if not normalized_keys or any(key not in canonical_keys for key in normalized_keys):
            raise SuccessorUpdateContractError(
                "exact successor staging refresh contains a noncanonical staging table"
            )
        data_dir = self._settings.data_dir
        csv_root = data_dir / "csv"
        parquet_root = data_dir / "parquet"
        if csv_root.is_symlink() or parquet_root.is_symlink() or sqlite_path.is_symlink():
            raise SuccessorUpdateContractError(
                "exact successor staging refresh refuses symlinked publication resources"
            )
        loaders = (
            SQLiteLoader(sqlite_path),
            CSVLoader(csv_root),
            ParquetLoader(parquet_root),
        )
        for staging_key in normalized_keys:
            safe_key = validate_sql_identifier(staging_key)
            frame = db.duckdb.execute(f"SELECT * FROM {safe_key}").pl()
            for loader in loaders:
                loader.load(safe_key, frame, mode="replace")

    @staticmethod
    def _successor_publication_staging_keys(
        db: DBManager,
        changed_staging_keys: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Add only conditional staging tables materialized in this candidate."""

        present_tables = {
            str(row[0])
            for row in db.duckdb.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
        return tuple(
            sorted(set(changed_staging_keys) | (CONDITIONAL_STAGING_KEYS & present_tables))
        )

    async def execute_successor_plan(
        self,
        plan: SuccessorExecutionPlan,
    ) -> SuccessorExecutionOutcome:
        """Execute all and only the sealed UPDATE dispatches, without sealing capture."""

        self._require_capture_session_admitted()
        transaction = self._successor_transaction
        assert transaction is not None
        resolved_entries = validate_successor_runtime_plan(transaction, plan)
        if self._successor_execution_plan is not None and (
            self._successor_execution_plan.to_dict() != plan.to_dict()
        ):
            raise SuccessorUpdateContractError(
                "successor execution plan changed after recovery authority was bound"
            )
        self._successor_execution_plan = plan
        changed_staging_keys = tuple(
            sorted(
                {
                    entry.staging_key
                    for dispatch_entries in resolved_entries
                    for entry in dispatch_entries
                }
            )
        )
        snapshot_at = datetime.fromisoformat(transaction.intent.as_of_utc.replace("Z", "+00:00"))
        support_date = snapshot_at.date()
        db, journal = self._init_db()
        runner: ExtractorRunner | None = None
        started = time.perf_counter()
        try:
            self._restore_successor_execution_state(journal)
            runner = self._build_runner(journal)
            for dispatch, resolved_dispatch_entries in zip(
                plan.dispatches, resolved_entries, strict=True
            ):
                if self._successor_dispatch_already_complete(dispatch):
                    continue
                entries = list(resolved_dispatch_entries)
                dispatch_order = dispatch.order
                dispatch_identity = dispatch.identity_sha256
                dispatch_pattern = dispatch.pattern

                def persist_dispatch(
                    frames: dict[str, pl.DataFrame],
                    _dispatch_order: int = dispatch_order,
                    _dispatch_identity: str = dispatch_identity,
                    _dispatch_pattern: str = dispatch_pattern,
                    **metadata: object,
                ) -> ChunkPersistenceAdmissionsV1:
                    return self._persist_staging_to_duckdb(
                        db,
                        frames,
                        run_mode="successor_exact",
                        lane_id=(f"successor.{_dispatch_order:06d}.{_dispatch_identity[:16]}"),
                        pattern=_dispatch_pattern,
                        chunk_index=_dispatch_order,
                        chunk_params=cast("list[dict]", metadata["chunk_params"]),
                        entries=cast("list[StagingEntry]", metadata["entries"]),
                        expected_staging_keys=cast("list[str]", metadata["expected_staging_keys"]),
                        source_results=cast("list[dict[str, object]]", metadata["source_results"]),
                        replace_existing_chunks=True,
                        materialize=False,
                    )

                self._active_successor_dispatch = dispatch
                try:
                    extraction = await runner.run_pattern_result(
                        dispatch.pattern,
                        [dispatch.parameters],
                        entries,
                        persist_chunk_results=persist_dispatch,
                        support_date=support_date,
                        required_route_ids=dispatch.staging_route_ids,
                        snapshot_at=snapshot_at,
                    )
                finally:
                    self._active_successor_dispatch = None
                if (
                    extraction.eligible_calls != 1
                    or extraction.support_skip_count != 0
                    or extraction.unattempted_eligible_calls != 0
                    or not extraction.is_complete
                    or extraction.errors
                ):
                    raise SuccessorUpdateContractError(
                        "sealed successor dispatch did not complete exactly once: "
                        f"order={dispatch.order}"
                    )

            self._require_complete_successor_receipts()
            self._materialize_staging_batches(db)
            self._export_successor_staging_resources(
                db,
                staging_keys=self._successor_publication_staging_keys(
                    db,
                    changed_staging_keys,
                ),
            )
            raw = self._load_staging_from_duckdb(db, include_empty=True)
            tables, rows, failed_loads = self._transform_and_load(
                db,
                raw,
                journal,
                mode="replace",
                require_complete_transforms=True,
                materialize_empty_outputs=True,
                include_live_transforms=True,
                successor_watermark_season=season_string(
                    snapshot_at.year if snapshot_at.month >= 10 else snapshot_at.year - 1
                ),
            )
            result = self._build_result(
                started,
                tables,
                rows,
                failed_loads,
                journal,
            )
            result.skipped_extractions = runner.skipped
            expected_transform_count = len(expected_transform_output_tables(include_live=True))
            if (
                tables != expected_transform_count
                or failed_loads != 0
                or len(self._transform_output_attestations) != expected_transform_count
                or not self._capture_result_is_complete(result)
            ):
                raise SuccessorUpdateContractError(
                    "exact successor execution did not load and attest the current "
                    "convention-discovered outputs"
                )
            return SuccessorExecutionOutcome(
                result=result,
                delta_receipts=self.successor_delta_receipts,
                transform_output_attestations=self.transform_output_attestations,
                planned_route_replacement_bindings_sha256=(
                    self.planned_route_replacement_bindings_sha256
                ),
            )
        finally:
            self._active_successor_dispatch = None
            if runner is not None:
                runner.shutdown()
            self._checkpoint_and_close_successor_database()

    def seal_successor_capture(self) -> PrivateGenerationIdentity:
        """Seal an admitted exact-plan capture only after its terminal receipt is durable."""

        self._require_complete_successor_receipts()
        expected_transform_count = len(expected_transform_output_tables(include_live=True))
        if len(self._transform_output_attestations) != expected_transform_count:
            raise SuccessorUpdateContractError(
                "successor capture cannot seal without the current convention-discovered "
                "transform attestations"
            )
        identity = self._seal_capture_session()
        if identity is None:
            raise SuccessorUpdateContractError(
                "successor capture cannot seal without a private capture session"
            )
        return identity

    def _build_result(
        self,
        start_time: float,
        tables: int,
        rows: int,
        failed_loads: int,
        journal: PipelineJournal,
        extra_errors: list[str] | None = None,
        *,
        include_exhausted: bool = False,
        include_abandoned: bool = False,
    ) -> PipelineResult:
        """Assemble a PipelineResult from collected counters."""
        failed_kwargs: dict[str, bool] = {}
        if include_exhausted:
            failed_kwargs["include_exhausted"] = True
        if include_abandoned:
            failed_kwargs["include_abandoned"] = True
        failed = journal.get_failed(**failed_kwargs)
        errors = [f"{ep}[{p}]: {err}" for ep, p, err in failed]
        if extra_errors:
            errors.extend(extra_errors)
        errors = list(dict.fromkeys(errors))
        result = PipelineResult()
        result.tables_updated = tables
        result.rows_total = rows
        result.failed_extractions = len(failed)
        result.failed_loads = failed_loads
        result.duration_seconds = time.perf_counter() - start_time
        result.errors = errors
        return result

    def _apply_extraction_outcome(
        self,
        result: PipelineResult,
        extraction: ExtractionOutcome,
    ) -> None:
        current_failures = extraction.failed_calls or extraction.pattern_failures
        if current_failures:
            result.failed_extractions = max(result.failed_extractions, current_failures)
        if extraction.errors:
            existing_errors = set(result.errors)
            for error in extraction.errors:
                if error in existing_errors:
                    continue
                result.errors.append(error)
                existing_errors.add(error)

    def _player_team_season_workloads(self) -> PlayerTeamSeasonWorkloadStore:
        duckdb_path = self._settings.duckdb_path
        if not isinstance(duckdb_path, Path):
            return PlayerTeamSeasonWorkloadStore.from_duckdb_path(None)
        store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path)
        store.promote_legacy_v3()
        return store

    def _discovery_artifacts(self) -> DiscoveryArtifactStore:
        duckdb_path = self._settings.duckdb_path
        if not isinstance(duckdb_path, Path):
            return DiscoveryArtifactStore.from_duckdb_path(None)
        return DiscoveryArtifactStore.from_duckdb_path(duckdb_path)

    def _extraction_progress(self) -> ExtractionProgressStore:
        duckdb_path = self._settings.duckdb_path
        if not isinstance(duckdb_path, Path):
            return ExtractionProgressStore.from_duckdb_path(None)
        return ExtractionProgressStore.from_duckdb_path(duckdb_path)

    def _persist_player_team_season_workloads(
        self,
        params: list[dict[str, int | str]],
        *,
        seasons: list[str],
        season_types: list[str],
        covered_pairs: set[tuple[str, str]],
    ) -> list[dict[str, int | str]]:
        if not covered_pairs:
            if params:
                raise ValueError(
                    "player/team workload rows require explicit covered season/type pairs"
                )
            return []
        store = self._player_team_season_workloads()
        store.upsert(params, covered_pairs=covered_pairs)
        return store.load_params(seasons=seasons, season_types=season_types)

    @staticmethod
    def _resolved_season_types(season_types: list[str] | None) -> list[str]:
        if season_types is None:
            return list(DEFAULT_SEASON_TYPES)
        return list(season_types)

    async def _discover_current_team_ids(
        self,
        discovery: _DiscoveryService,
        *,
        seasons: list[str],
        refresh: bool = False,
    ) -> list[int]:
        artifacts = self._discovery_artifacts()
        scope = DiscoveryArtifactScope(kind="current_team_ids", seasons=tuple(seasons))
        cached = [] if refresh else artifacts.load_ids(scope)
        if cached:
            return cached
        discovered = await discovery.discover_current_team_ids()
        artifacts.upsert_ids(scope, discovered, provenance="discovery")
        return discovered

    async def _discover_player_team_season_result(
        self,
        discovery: _DiscoveryService,
        *,
        seasons: list[str],
        season_types: list[str],
        run_mode: str = "init",
    ) -> PlayerTeamSeasonDiscoveryResult:
        requested_pairs = frozenset(
            (season, season_type) for season in seasons for season_type in season_types
        )
        mutable_pairs = (
            frozenset((seasons[-1], season_type) for season_type in season_types)
            if seasons and run_mode in {"daily", "monthly"}
            else frozenset()
        )
        store = self._player_team_season_workloads()
        artifact_path = store.artifact_path
        manifest_path = store.manifest_path
        cache_files_present = (
            artifact_path is not None
            and artifact_path.is_file()
            and manifest_path is not None
            and manifest_path.is_file()
        )
        cached_pairs: set[tuple[str, str]] = set()
        if cache_files_present:
            coverage = store.load_coverage(
                seasons=seasons,
                season_types=season_types,
            )
            cached_pairs = coverage.covered_pairs - mutable_pairs
            if coverage.invalid_pairs:
                logger.info(
                    (
                        "player/team workload cache has invalid pair evidence; "
                        "using live discovery: {}"
                    ),
                    sorted(coverage.invalid_pairs),
                )
            if requested_pairs <= cached_pairs:
                logger.info(
                    "reusing player/team workload cache for all {} requested season/type pairs",
                    len(requested_pairs),
                )
                return PlayerTeamSeasonDiscoveryResult(
                    params=store.load_params(
                        seasons=seasons,
                        season_types=season_types,
                    ),
                    requested_pairs=requested_pairs,
                    covered_pairs=requested_pairs,
                    upstream_unavailable_pairs=_classified_upstream_unavailable_pairs(
                        requested_pairs
                    ),
                )
        elif (
            artifact_path is not None
            and artifact_path.exists()
            or manifest_path is not None
            and manifest_path.exists()
        ):
            logger.info("player/team workload cache files are incomplete; using live discovery")

        live_required_pairs = requested_pairs - cached_pairs
        grouped_live_scopes = _group_exact_pairs(
            live_required_pairs,
            seasons=seasons,
            season_types=season_types,
        )
        logger.info(
            (
                "using live player/team discovery for {} {} pair(s) "
                "across {} exact scope(s) in {} mode"
            ),
            len(live_required_pairs),
            "mutable or uncached" if mutable_pairs else "uncached",
            len(grouped_live_scopes),
            run_mode,
        )
        retained_cached_pairs = cached_pairs - set(live_required_pairs)
        cached_params = (
            store.load_params(
                seasons=seasons,
                season_types=season_types,
            )
            if retained_cached_pairs
            else []
        )
        merged_params: dict[tuple[int, int, str, str], dict[str, int | str]] = {}
        for raw_param in cached_params:
            pair = (str(raw_param["season"]), str(raw_param["season_type"]))
            if pair not in retained_cached_pairs:
                continue
            key = (
                int(raw_param["player_id"]),
                int(raw_param["team_id"]),
                pair[0],
                pair[1],
            )
            merged_params[key] = {
                "player_id": key[0],
                "team_id": key[1],
                "season": key[2],
                "season_type": key[3],
            }

        covered_pairs = set(retained_cached_pairs)
        upstream_unavailable_pairs = _classified_upstream_unavailable_pairs(retained_cached_pairs)
        for live_seasons, live_season_types in grouped_live_scopes:
            expected_pairs = {
                (season, season_type)
                for season in live_seasons
                for season_type in live_season_types
            }
            live_result = await discovery.discover_player_team_season_params_result(
                list(live_seasons),
                season_types=list(live_season_types),
            )
            live_covered_pairs = expected_pairs & set(live_result.covered_pairs)
            covered_pairs.update(live_covered_pairs)
            upstream_unavailable_pairs.update(
                {
                    pair: reason
                    for pair, reason in live_result.upstream_unavailable_pairs.items()
                    if pair in live_covered_pairs
                }
            )
            for raw_param in live_result.params:
                pair = (str(raw_param["season"]), str(raw_param["season_type"]))
                if pair not in live_covered_pairs:
                    continue
                key = (
                    int(raw_param["player_id"]),
                    int(raw_param["team_id"]),
                    pair[0],
                    pair[1],
                )
                merged_params[key] = {
                    "player_id": key[0],
                    "team_id": key[1],
                    "season": key[2],
                    "season_type": key[3],
                }

        for pair, reason in _classified_upstream_unavailable_pairs(covered_pairs).items():
            upstream_unavailable_pairs.setdefault(pair, reason)

        return PlayerTeamSeasonDiscoveryResult(
            params=[merged_params[key] for key in sorted(merged_params)],
            requested_pairs=requested_pairs,
            covered_pairs=frozenset(covered_pairs),
            upstream_unavailable_pairs=upstream_unavailable_pairs,
        )

    @staticmethod
    def _require_complete_game_discovery(
        result: GameDiscoveryResult,
        *,
        requested_combos: frozenset[tuple[str, str]] | None = None,
    ) -> None:
        required_combos = result.requested_combos if requested_combos is None else requested_combos
        explicitly_covered = result.requested_combos & result.covered_combos
        concrete_frames = frozenset(result.frames_by_combo)
        if required_combos <= explicitly_covered and required_combos <= concrete_frames:
            return
        missing_combos = sorted(required_combos - explicitly_covered)
        missing_frames = sorted(required_combos - concrete_frames)
        details = []
        if missing_combos:
            details.append(f"missing season/season_type combos: {missing_combos}")
        if missing_frames:
            details.append(f"missing exact combo frames: {missing_frames}")
        raise InitDiscoveryCoverageError([f"incomplete game discovery; {'; '.join(details)}"])

    @staticmethod
    def _require_complete_player_team_discovery(
        result: PlayerTeamSeasonDiscoveryResult,
    ) -> None:
        if result.is_complete:
            return
        missing_pairs = sorted(result.requested_pairs - result.covered_pairs)
        raise InitDiscoveryCoverageError(
            [f"incomplete player-team-season discovery; missing pairs: {missing_pairs}"]
        )

    async def _discover_complete_historical_player_union(
        self,
        discovery: _DiscoveryService,
        *,
        seasons: list[str],
    ) -> list[int]:
        """Build a monthly player scope from exact complete per-season evidence."""

        requested_seasons = tuple(dict.fromkeys(seasons))
        if not requested_seasons:
            raise InitDiscoveryCoverageError(["historical player discovery has no seasons"])
        raw_results = await asyncio.gather(
            *(
                discovery.discover_all_player_ids_result(season=season)
                for season in requested_seasons
            ),
            return_exceptions=True,
        )
        failures: list[str] = []
        ids_by_season: dict[str, list[int]] = {}
        for season, raw_result in zip(requested_seasons, raw_results, strict=True):
            if isinstance(raw_result, Exception):
                failures.append(
                    f"historical player discovery failed for {season}: {type(raw_result).__name__}"
                )
                continue
            if not isinstance(raw_result, PlayerIdDiscoveryResult):
                failures.append(
                    f"historical player discovery returned invalid evidence for {season}"
                )
                continue
            if raw_result.requested_season != season:
                failures.append(f"historical player discovery scope mismatch for {season}")
                continue
            if not raw_result.is_complete or not raw_result.ids:
                failure_kind = raw_result.failure_kind or "no_data"
                failures.append(
                    f"historical player discovery incomplete for {season}: {failure_kind}"
                )
                continue
            if any(type(player_id) is not int or player_id <= 0 for player_id in raw_result.ids):
                failures.append(f"historical player discovery returned invalid IDs for {season}")
                continue
            ids_by_season[season] = sorted(set(raw_result.ids))

        if failures:
            raise InitDiscoveryCoverageError(failures)

        artifacts = self._discovery_artifacts()
        for season, player_ids in ids_by_season.items():
            artifacts.upsert_ids(
                DiscoveryArtifactScope(
                    kind="player_ids_all",
                    seasons=(season,),
                    variant="historical",
                ),
                player_ids,
                provenance="per-season-discovery",
            )
        union_ids = sorted(
            {player_id for player_ids in ids_by_season.values() for player_id in player_ids}
        )
        artifacts.upsert_ids(
            DiscoveryArtifactScope(
                kind="player_ids_all",
                seasons=requested_seasons,
                variant="historical",
            ),
            union_ids,
            provenance="per-season-discovery-union",
        )
        player_ids = _apply_player_shard(union_ids)
        if self._progress is not None:
            self._progress.log_discovery("players", len(player_ids))
        return player_ids

    def _admit_successor_provider_call(
        self,
        endpoint_name: str,
        params: dict[str, object],
        result_route_ids: tuple[str, ...],
    ) -> None:
        """Fail before any provider call unless its exact route/scope is in intent."""

        transaction = self._successor_transaction
        if transaction is None:
            raise SuccessorUpdateContractError(
                "successor provider call admission requires an immutable update intent"
            )
        self._require_successor_registry_authority(endpoint_name=endpoint_name)
        from nbadb.contracts.staging_route_contract import staging_route_contract_bundle

        routes = staging_route_contract_bundle().by_route_id
        try:
            canonical_params = canonical_parameters_payload(params)
            scope_sha256 = canonical_parameters_sha256(canonical_params)
        except (TypeError, ValueError) as exc:
            raise SuccessorUpdateContractError(
                "successor provider call parameters are not canonical JSON"
            ) from exc
        if (
            not result_route_ids
            or len(result_route_ids) != len(set(result_route_ids))
            or any(not isinstance(route_id, str) or not route_id for route_id in result_route_ids)
        ):
            raise SuccessorUpdateContractError(
                "successor provider call requires unique exact staging routes"
            )

        active_dispatch = self._active_successor_dispatch
        if active_dispatch is not None:
            if (
                active_dispatch.endpoint_name != endpoint_name
                or active_dispatch.parameters_sha256 != scope_sha256
                or active_dispatch.parameters != canonical_params
                or set(active_dispatch.staging_route_ids) != set(result_route_ids)
            ):
                raise SuccessorUpdateContractError(
                    "provider call differs from the active sealed execution dispatch"
                )
            parameter_scopes = active_dispatch.requested_scopes
        else:
            parameter_scopes = tuple(
                scope
                for scope in transaction.intent.requested_scopes
                if scope.scope_sha256 == scope_sha256 and scope.parameters == canonical_params
            )
        expected_route_ids = {
            scope.route_id
            for scope in parameter_scopes
            if (route := routes.get(scope.route_id)) is not None
            and route.endpoint_name == endpoint_name
        }
        if set(result_route_ids) != expected_route_ids:
            raise SuccessorUpdateContractError(
                "successor provider call routes or parameters fall outside the immutable intent"
            )

        scopes_by_uniqueness = {scope.uniqueness_key: scope for scope in parameter_scopes}
        for route_id in result_route_ids:
            route = routes.get(route_id)
            scope = (
                scopes_by_uniqueness.get(
                    (endpoint_name, route_id, route.contract_sha256, scope_sha256)
                )
                if route is not None
                else None
            )
            if (
                route is None
                or scope is None
                or route.endpoint_name != endpoint_name
                or route.provider_authority_sha256 != transaction.baseline.provider_authority_sha256
                or scope.route_contract_sha256 != route.contract_sha256
                or scope.scope_sha256 != scope_sha256
                or scope.parameters != canonical_params
            ):
                raise SuccessorUpdateContractError(
                    "successor provider call differs from route, provider, contract, or parameters"
                )

    def _admit_successor_conditional_result_routes(
        self,
        endpoint_name: str,
        params: dict[str, object],
        static_route_ids: tuple[str, ...],
        conditional_route_ids: tuple[str, ...],
    ) -> None:
        """Admit one typed receipt-verified route without widening pre-call intent."""

        transaction = self._successor_transaction
        if transaction is None:
            raise SuccessorUpdateContractError(
                "conditional successor route admission requires an immutable update intent"
            )
        self._require_capture_session_admitted()
        self._admit_successor_provider_call(endpoint_name, params, static_route_ids)
        from nbadb.contracts.staging_route_contract import (
            admit_known_conditional_staging_route,
        )

        try:
            admit_known_conditional_staging_route(
                endpoint_name=endpoint_name,
                static_route_ids=static_route_ids,
                conditional_route_ids=conditional_route_ids,
                provider_authority_sha256=transaction.baseline.provider_authority_sha256,
            )
        except ValueError as exc:
            raise SuccessorUpdateContractError(
                "conditional successor route differs from typed response authority"
            ) from exc

    def _require_live_w2_authority_factories(
        self,
    ) -> tuple[RawRequestCaptureContextFactory, LivePlanAuthorityBindingFactory]:
        """Return the explicit external authorities required by every live call."""

        raw_factory = self._live_raw_request_capture_context_factory
        plan_factory = self._live_plan_authority_binding_factory
        if raw_factory is None or plan_factory is None:
            raise ParserInputCaptureIntegrityError(
                "live extraction lacks explicit Raw V2 context and authenticated sealed-plan "
                "authority factories"
            )
        if self._raw_request_execution_identity is None or self._w2_preparation_runtime is None:
            raise ParserInputCaptureIntegrityError(
                "live extraction lacks exact Raw Authority V2 and W2 runtime resources"
            )
        return raw_factory, plan_factory

    @staticmethod
    def _live_source_result_metadata(
        source_call: LiveSourceCallResult,
    ) -> dict[str, object]:
        """Replay and retain every source authority needed by W2 persistence."""

        binding, raw_snapshot, live_plan, expected_live_plan_sha256 = (
            source_call.replay_exact_source_evidence()
        )
        frames = source_call.frames
        if not source_call.expected_staging_keys or (
            set(frames) != set(source_call.expected_staging_keys)
        ):
            raise ParserInputCaptureIntegrityError("live source call has incomplete staging frames")
        return {
            "frames": frames,
            "source_endpoint_name": source_call.endpoint_name,
            "source_params_json": source_call.parameters_json,
            "expected_staging_keys": source_call.expected_staging_keys,
            "receipt_binding": binding,
            "result_route_ids_by_staging_key": (source_call.result_route_ids_by_staging_key),
            "raw_request_capture_snapshot": raw_snapshot,
            "plan_live_snapshot_at": live_plan.live_snapshot_at,
            "live_plan_bindings": ((live_plan, expected_live_plan_sha256),),
        }

    def _start_live_w2_journal_calls(
        self,
        source_calls: tuple[LiveSourceCallResult, ...],
    ) -> PipelineJournal:
        """Open exact W2-required rows before any live staging mutation."""

        journal = self._journal
        if journal is None:
            raise ParserInputCaptureIntegrityError(
                "live W2 persistence requires an initialized extraction journal"
            )
        seen: set[tuple[str, str]] = set()
        ordered_keys: list[tuple[str, str]] = []
        for source_call in source_calls:
            key = (source_call.endpoint_name, source_call.parameters_json)
            if key in seen:
                raise ParserInputCaptureIntegrityError(
                    "live source-call inventory repeats one journal identity"
                )
            seen.add(key)
            ordered_keys.append(key)
        for key in ordered_keys:
            if journal.was_extracted(
                *key,
                require_receipt=True,
                require_w2_operation=True,
            ):
                raise ParserInputCaptureIntegrityError(
                    "live source-call inventory attempts to replace an already complete "
                    "W2 journal identity"
                )
        for key in ordered_keys:
            journal.record_start(
                *key,
                require_receipt=True,
                require_w2_operation=True,
            )
        return journal

    @staticmethod
    def _complete_live_w2_journal_calls(
        journal: PipelineJournal,
        source_calls: tuple[LiveSourceCallResult, ...],
        admissions: ChunkPersistenceAdmissionsV1,
    ) -> None:
        """Replay ordered W2 admissions and only then expose journal success."""

        from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1

        if type(admissions) is not tuple or len(admissions) != len(source_calls):
            raise ParserInputCaptureIntegrityError(
                "live W2 admission inventory differs from ordered source calls"
            )
        seen_admissions: set[str] = set()
        seen_calls: set[str] = set()
        for source_call, admission in zip(source_calls, admissions, strict=True):
            binding, _raw_snapshot, _live_plan, _plan_pin = (
                source_call.replay_exact_source_evidence()
            )
            if type(admission) is not W2SourceCallAdmissionV1:
                raise ParserInputCaptureIntegrityError(
                    "live persistence returned a foreign W2 admission"
                )
            try:
                replayed = W2SourceCallAdmissionV1.from_canonical_bytes(admission.canonical_bytes())
            except Exception:
                raise ParserInputCaptureIntegrityError(
                    "live W2 admission failed exact canonical replay"
                ) from None
            if (
                replayed is admission
                or replayed != admission
                or replayed.logical_call_receipt_sha256 != binding.logical_call_receipt_sha256
                or replayed.admission_sha256 in seen_admissions
                or replayed.logical_call_receipt_sha256 in seen_calls
            ):
                raise ParserInputCaptureIntegrityError(
                    "live W2 admission differs from ordered source-call authority"
                )
            seen_admissions.add(replayed.admission_sha256)
            seen_calls.add(replayed.logical_call_receipt_sha256)
            journal.record_success(
                source_call.endpoint_name,
                source_call.parameters_json,
                sum(frame.height for frame in source_call.frames.values()),
                receipt_binding=binding,
                w2_admission=replayed,
            )

    def _extract_successor_live_snapshot(self) -> LiveSnapshotExtraction:
        session = self._capture_session
        transaction = self._successor_transaction
        if transaction is None or session is None:
            raise SuccessorUpdateContractError(
                "successor live extraction requires intent and private capture"
            )
        if self._successor_execution_plan is not None:
            self._reject_later_derived_successor_fanout(surface="live snapshot")
        self._require_capture_session_admitted()
        raw_context_factory, live_plan_factory = self._require_live_w2_authority_factories()
        return LiveSnapshotWarehouse(
            settings=self._settings,
            capture_contract_factory=session.contract_for,
            call_admission=self._admit_successor_provider_call,
            conditional_route_admission=self._admit_successor_conditional_result_routes,
            raw_request_capture_context_factory=raw_context_factory,
            live_plan_authority_binding_factory=live_plan_factory,
        ).extract_source_calls(
            snapshot_at=datetime.fromisoformat(transaction.intent.as_of_utc.replace("Z", "+00:00"))
        )

    def _persist_successor_live_snapshot(
        self,
        db: DBManager,
        *,
        run_mode: str,
    ) -> LiveSnapshotExtraction:
        """Persist each live source call as a route-local replacement receipt."""

        snapshot = self._extract_successor_live_snapshot()
        snapshot.replay_exact_source_evidence()
        journal = self._start_live_w2_journal_calls(snapshot.source_calls)
        for call_index, source_call in enumerate(snapshot.source_calls):
            source_result = self._live_source_result_metadata(source_call)
            binding = cast("LogicalCallReceiptBinding", source_result["receipt_binding"])
            params = source_call.params
            frames = cast("dict[str, pl.DataFrame]", source_result["frames"])
            admissions = self._persist_staging_to_duckdb(
                db,
                frames,
                run_mode=run_mode,
                lane_id=(
                    f"{run_mode}.live.{call_index:04d}.{binding.logical_parameters_sha256[:16]}"
                ),
                pattern="live",
                chunk_index=call_index,
                chunk_params=[params],
                entries=get_by_endpoint(source_call.endpoint_name),
                expected_staging_keys=list(source_call.expected_staging_keys),
                source_results=[source_result],
                materialize=False,
            )
            self._complete_live_w2_journal_calls(
                journal,
                (source_call,),
                admissions,
            )
        snapshot.release_source_evidence()
        if not snapshot.game_ids:
            logger.bind(run_mode=run_mode).info(
                "successor live snapshot: scoreboard closed with no active games"
            )
        return snapshot

    def _persist_recurring_live_snapshot(
        self,
        db: DBManager,
        *,
        run_mode: Literal["daily", "monthly"],
    ) -> LiveSnapshotExtraction:
        """Atomically persist one complete public recurring live snapshot.

        The live warehouse supplies real content-bound response and logical-call
        receipts without retaining a private parser-input generation. Every
        provider call contributes all of its fixed wide routes plus the typed
        lossless node route in one StagingBatchStore transaction.
        """

        if self._successor_transaction is not None or self._capture_session is not None:
            raise SuccessorUpdateContractError(
                "public recurring live persistence cannot replace explicit successor capture"
            )
        raw_context_factory, live_plan_factory = self._require_live_w2_authority_factories()
        snapshot = LiveSnapshotWarehouse(
            settings=self._settings,
            public_recurring=True,
            raw_request_capture_context_factory=raw_context_factory,
            live_plan_authority_binding_factory=live_plan_factory,
        ).extract_source_calls()
        snapshot.replay_exact_source_evidence()
        if not snapshot.source_calls:
            raise ParserInputCaptureIntegrityError(
                "recurring live extraction returned no scoreboard source call"
            )

        expected_call_identities: list[tuple[str, str]] = [
            ("live_score_board", "{}"),
        ]
        if snapshot.game_ids:
            expected_call_identities.append(("live_odds", "{}"))
            for game_id in snapshot.game_ids:
                if not isinstance(game_id, str) or not game_id:
                    raise ParserInputCaptureIntegrityError(
                        "recurring live extraction returned an invalid game identity"
                    )
                params_json = json.dumps(
                    {"game_id": game_id},
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
                expected_call_identities.extend(
                    (
                        ("live_play_by_play", params_json),
                        ("live_box_score", params_json),
                    )
                )
        observed_call_identities = [
            (source_call.endpoint_name, source_call.parameters_json)
            for source_call in snapshot.source_calls
        ]
        if observed_call_identities != expected_call_identities:
            raise ParserInputCaptureIntegrityError(
                "recurring live extraction source-call inventory is incomplete"
            )

        source_results: list[dict[str, object]] = []
        all_entries: list[StagingEntry] = []
        observed_static_keys: set[str] = set()
        for source_call in snapshot.source_calls:
            source_result = self._live_source_result_metadata(source_call)
            frames = cast("dict[str, pl.DataFrame]", source_result["frames"])
            expected_keys = source_call.expected_staging_keys
            binding = cast("LogicalCallReceiptBinding", source_result["receipt_binding"])
            route_mapping = source_call.result_route_ids_by_staging_key
            entries = get_by_endpoint(source_call.endpoint_name)
            static_keys = tuple(entry.staging_key for entry in entries)
            expected_static_routes = {
                entry.staging_key: (
                    f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
                )
                for entry in entries
            }
            observed_routes = dict(route_mapping)
            if (
                not expected_keys
                or len(expected_keys) != len(set(expected_keys))
                or set(frames) != set(expected_keys)
                or len(observed_routes) != len(route_mapping)
                or set(observed_routes) != set(expected_keys)
                or LIVE_LOSSLESS_STAGING_KEY not in frames
                or frames[LIVE_LOSSLESS_STAGING_KEY].is_empty()
                or {key: observed_routes.get(key) for key in static_keys} != expected_static_routes
                or binding.result_route_ids != tuple(sorted(observed_routes.values()))
            ):
                raise ParserInputCaptureIntegrityError(
                    "recurring live source call lacks complete receipt-bound staging frames"
                )
            observed_static_keys.update(static_keys)
            all_entries.extend(entries)
            source_results.append(source_result)

        expected_static_keys = {
            entry.staging_key
            for endpoint_name, _params_json in expected_call_identities
            for entry in get_by_endpoint(endpoint_name)
        }
        if observed_static_keys != expected_static_keys:
            raise ParserInputCaptureIntegrityError(
                "recurring live extraction did not retain every fixed live frame"
            )

        journal = self._start_live_w2_journal_calls(snapshot.source_calls)
        admissions = self._persist_staging_to_duckdb(
            db,
            {},
            run_mode=run_mode,
            lane_id=f"{run_mode}.live.snapshot",
            pattern="live",
            chunk_index=0,
            chunk_params=[source_call.params for source_call in snapshot.source_calls],
            entries=all_entries,
            source_results=source_results,
            replace_existing_chunks=True,
            materialize=False,
        )
        self._complete_live_w2_journal_calls(
            journal,
            snapshot.source_calls,
            admissions,
        )
        snapshot.release_source_evidence()
        if not snapshot.game_ids:
            logger.bind(run_mode=run_mode).info(
                "recurring live snapshot: scoreboard closed with no active games"
            )
        return snapshot

    def _transform_and_load(
        self,
        db: DBManager,
        raw: dict[str, pl.DataFrame],
        journal: PipelineJournal,
        mode: LoadMode = "replace",
        *,
        require_complete_transforms: bool = False,
        materialize_empty_outputs: bool = False,
        include_live_transforms: bool = False,
        successor_watermark_season: str | None = None,
    ) -> tuple[int, int, int]:
        """Run transform pipeline then load all outputs.

        Returns (tables_updated, rows_total, failed_loads).
        The transform pipeline connection is always cleaned up via
        try/finally to prevent DuckDB connection leaks (QUAL-010).
        """
        pp = self._progress
        self._transform_output_attestations = ()
        if successor_watermark_season is not None and self._successor_transaction is None:
            raise SuccessorUpdateContractError(
                "fixed successor watermark season requires an exact successor transaction"
            )
        watermark_season = successor_watermark_season or current_season()

        # Build staging dict (LazyFrames)
        staging: dict[str, pl.LazyFrame] = {key: df.lazy() for key, df in raw.items()}

        # Transform
        transformers = discover_all_transformers(include_live=include_live_transforms)
        require_complete_transformer_universe(
            transformers,
            include_live=include_live_transforms,
        )
        pipeline = TransformPipeline(db.duckdb)
        pipeline.register_all(transformers)
        n_transformers = len(transformers)
        if pp is not None:
            pp.start_pattern(f"Transform ({n_transformers})", total=n_transformers)
        try:
            outputs = pipeline.run(
                staging,
                validate_input_schemas=True,
                require_complete=require_complete_transforms,
                on_progress=pp,
            )
        finally:
            # TransformPipeline.run() resets _conn in its own finally,
            # but we guard here as well for safety.
            pass

        # Load
        loader = create_multi_loader(self._settings, duckdb_conn=db.duckdb)
        tables_updated = 0
        rows_total = 0
        failed_loads = 0
        loaded_attestations: list[TransformOutputAttestation] = []
        loadable = (
            outputs
            if materialize_empty_outputs
            else {table: df for table, df in outputs.items() if not df.is_empty()}
        )
        if pp is not None:
            pp.start_pattern(f"Load ({len(loadable)})", total=len(loadable))

        for table, df in outputs.items():
            if df.is_empty() and not materialize_empty_outputs:
                logger.debug("skip load (empty): {}", table)
                continue
            try:
                loader.load(table, df, mode=mode)
                rows = df.shape[0]
                loaded_attestations.append(
                    TransformOutputAttestation(
                        table_name=table,
                        row_count=rows,
                        schema_sha256=frame_schema_hash(df),
                        content_sha256=frame_content_hash(df),
                    )
                )
                tables_updated += 1
                rows_total += rows
                if pp is not None:
                    pp.advance_pattern(success=True, rows=rows)
            except Exception as exc:
                failed_loads += 1
                logger.error("load failed for {}: {}", table, type(exc).__name__)
                if pp is not None:
                    pp.advance_pattern(success=False)
                continue  # skip watermark if load failed

            try:
                journal.set_watermark(table, "last_load", watermark_season, rows)
            except Exception as wm_exc:
                logger.warning(
                    "watermark write failed for {}: {}",
                    table,
                    type(wm_exc).__name__,
                )

            try:
                quality_score: float | None = None
                try:
                    monitor = DataQualityMonitor(db.duckdb)
                    quality_score = monitor.record_table_quality_checks(
                        table,
                        row_count=rows,
                    )
                except Exception as dq_exc:
                    logger.debug(
                        "quality score skipped for {}: {}",
                        table,
                        type(dq_exc).__name__,
                    )
                journal.record_table_metadata(
                    table,
                    rows,
                    schema_hash_for_frame(df),
                    quality_score=quality_score,
                )
            except Exception as meta_exc:
                logger.warning(
                    "metadata write failed for {}: {}",
                    table,
                    type(meta_exc).__name__,
                )

            logger.info(
                "loaded {}: {} rows ({})",
                table,
                rows,
                mode,
            )

        expected_output_tables = {transformer.output_table for transformer in transformers}
        attested_output_tables = {attestation.table_name for attestation in loaded_attestations}
        if (
            require_complete_transforms
            and materialize_empty_outputs
            and failed_loads == 0
            and len(loaded_attestations) == len(expected_output_tables)
            and attested_output_tables == expected_output_tables
        ):
            if self._successor_transaction is None:
                self._transform_output_attestations = tuple(
                    sorted(loaded_attestations, key=lambda item: item.table_name)
                )
            else:
                data_dir = self._settings.data_dir
                if not isinstance(data_dir, Path):
                    raise SuccessorUpdateContractError(
                        "successor transform readback requires an explicit data directory"
                    )
                scratch_parent, scratch_identity, scratch_max_bytes = (
                    self._require_successor_transform_scratch_authority()
                )
                readback = build_successor_transform_attestations(
                    db.duckdb,
                    scratch_parent=scratch_parent,
                    expected_scratch_parent_identity=scratch_identity,
                    transform_scratch_max_bytes=scratch_max_bytes,
                )
                if sum(item.row_count for item in readback) != rows_total:
                    raise SuccessorUpdateContractError(
                        "successor DuckDB transform row counts differ from loaded outputs"
                    )
                self._transform_output_attestations = readback

        return tables_updated, rows_total, failed_loads

    def _staging_store_for(self, db: DBManager) -> StagingBatchStore:
        """Reuse one stateless store for the lifetime of its exact connection."""

        connection = db.duckdb
        if (
            self._staging_batch_store is not None
            and self._staging_batch_store_connection is connection
        ):
            return self._staging_batch_store
        store = StagingBatchStore(connection)
        self._staging_batch_store = store
        self._staging_batch_store_connection = connection
        return store

    def _bind_raw_request_snapshot_to_logical_call(
        self,
        snapshot: RawRequestCaptureSnapshotV2,
        binding: LogicalCallReceiptBinding,
        pending_request_observations: object = None,
    ) -> RawRequestCaptureSnapshotV2:
        """Project the runner's exact logical receipt onto its public sidecar.

        The private capture contract owns the logical-call receipt and the
        extractor-owned public sidecar owns the provider attempts.  They meet
        only after the runner has finalized the logical call, so persistence
        performs this immutable, fail-closed join before raw finalization.
        """

        from nbadb.extract.raw_request_capture import (
            PendingRawRequestSuccessV2,
            RawRequestCaptureSnapshotV2,
        )

        if type(snapshot) is not RawRequestCaptureSnapshotV2:
            raise ParserInputCaptureIntegrityError(
                "raw-request logical binding requires an exact capture snapshot"
            )
        if type(binding) is not LogicalCallReceiptBinding:
            raise ParserInputCaptureIntegrityError(
                "raw-request logical binding requires an exact receipt binding"
            )
        pending_rows = snapshot.pending_successes
        if not pending_rows:
            raise ParserInputCaptureIntegrityError(
                "raw-request logical binding has no pending public success"
            )
        already_bound = all(
            pending.logical_receipt_sha256 == binding.logical_call_receipt_sha256
            and pending.aggregate_route_ids == binding.result_route_ids
            for pending in pending_rows
        )
        if already_bound:
            return snapshot
        if any(
            pending.logical_receipt_sha256 is not None or pending.aggregate_route_ids
            for pending in pending_rows
        ):
            raise ParserInputCaptureIntegrityError(
                "raw-request public success has a partial logical binding"
            )
        receipt_factory = self._receipt_only_capture_factory
        if receipt_factory is None:
            if (
                type(pending_request_observations) is not tuple
                or len(pending_request_observations) != 1
                or len(pending_rows) != 1
                or type(pending_request_observations[0]) is not PendingRequestObservation
            ):
                raise ParserInputCaptureIntegrityError(
                    "raw-request public success lacks a receipt-only selection authority"
                )
            pending_closure = pending_request_observations[0]
            pending_public = pending_rows[0]
            public_body = pending_public.body_object
            if (
                pending_closure.result_contract != "lossless_drift"
                or pending_closure.bronze_result_sets
                or pending_closure.source_family != "stats"
                or pending_closure.response_receipt_sha256 != pending_public.private_receipt_sha256
                or pending_closure.retry_ordinal != pending_public.attempt.retry_ordinal
                or pending_closure.request_ordinal != pending_public.attempt.request_ordinal
                or pending_closure.endpoint_id != pending_public.attempt.endpoint_id
                or pending_closure.provider_authority_sha256 != binding.provider_authority_sha256
                or pending_closure.provider_authority_sha256
                != pending_public.attempt.provider_authority_sha256
                or pending_closure.endpoint_contract_sha256
                != pending_public.attempt.endpoint_contract_sha256
                or pending_closure.logical_call_receipt_sha256
                != binding.logical_call_receipt_sha256
                or pending_closure.logical_parameters_sha256 != binding.logical_parameters_sha256
                or public_body is None
                or pending_closure.response_body_sha256 != public_body.response_sha256
                or pending_closure.response_body_bytes != public_body.uncompressed_bytes
            ):
                raise ParserInputCaptureIntegrityError(
                    "lossless raw-request success differs from typed pending closure evidence"
                )
            selected_receipt = binding.logical_call_receipt_sha256
            selected_routes = binding.result_route_ids
        else:
            selected_receipt, selected_routes = receipt_factory.sink.exact_logical_selection(
                tuple(pending.private_receipt_sha256 for pending in pending_rows)
            )
        if (
            selected_receipt != binding.logical_call_receipt_sha256
            or selected_routes != binding.result_route_ids
        ):
            raise ParserInputCaptureIntegrityError(
                "raw-request receipt-only selection differs from its logical binding"
            )
        bound_pending: list[PendingRawRequestSuccessV2] = []
        for pending in pending_rows:
            if (
                type(pending) is not PendingRawRequestSuccessV2
                or pending.attempt.provider_authority_sha256 != binding.provider_authority_sha256
            ):
                raise ParserInputCaptureIntegrityError(
                    "raw-request public success differs from its logical receipt"
                )
            bound_pending.append(
                replace(
                    pending,
                    logical_receipt_sha256=binding.logical_call_receipt_sha256,
                    aggregate_route_ids=binding.result_route_ids,
                )
            )
        return replace(snapshot, pending_successes=tuple(bound_pending))

    def _persist_staging_to_duckdb(
        self,
        db: DBManager,
        raw: dict[str, pl.DataFrame],
        *,
        run_mode: str = "unknown",
        lane_id: str = "manual",
        pattern: str = "unknown",
        chunk_index: int = 0,
        chunk_params: list[dict] | None = None,
        entries: list[StagingEntry] | list[object] | None = None,
        expected_staging_keys: list[str] | None = None,
        source_results: list[dict[str, object]] | None = None,
        failure_raw_request_capture_snapshots: tuple[
            RawRequestCaptureSnapshotV2,
            ...,
        ] = (),
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
        raw_request_closure_build: ProductionRequestClosureBuild | None = None,
        raw_request_terminal: bool = False,
        dedupe_materialized: bool | None = None,
        replace_existing_chunks: bool = False,
        materialize: bool = True,
    ) -> tuple[W2SourceCallAdmissionV1, ...]:
        """Persist in-memory staging DataFrames to DuckDB tables.

        Ensures staging data survives process crashes between extraction
        and transform phases without dropping prior persisted rows from
        earlier iterations or resumed shards.
        """
        from nbadb.extract.raw_request_capture import RawRequestCaptureSnapshotV2

        if type(failure_raw_request_capture_snapshots) is not tuple or any(
            type(snapshot) is not RawRequestCaptureSnapshotV2
            for snapshot in failure_raw_request_capture_snapshots
        ):
            raise ParserInputCaptureIntegrityError(
                "failed raw-request snapshot inventory is invalid"
            )
        if source_results is not None and (
            not isinstance(source_results, list)
            or any(not isinstance(source_result, dict) for source_result in source_results)
        ):
            raise ParserInputCaptureIntegrityError(
                "staging source results must be a list of dictionaries"
            )
        if (
            raw_request_closure_build is not None
            and type(raw_request_closure_build) is not ProductionRequestClosureBuild
        ):
            raise ParserInputCaptureIntegrityError(
                "raw-request persistence has an invalid closure build"
            )
        if type(raw_request_terminal) is not bool:
            raise ParserInputCaptureIntegrityError(
                "raw-request terminal flag must be an exact boolean"
            )
        if raw_request_terminal and (
            raw
            or source_results
            or failure_raw_request_capture_snapshots
            or expected_staging_keys
            or chunk_params
            or entries
        ):
            raise ParserInputCaptureIntegrityError(
                "raw-request terminal sealing cannot carry staging or request evidence"
            )
        raw_request_capture_active = self._raw_request_execution_identity is not None
        manifest_stats_authority = (
            raw_request_closure_build.authority
            if raw_request_closure_build is not None
            else request_closure_authority
        )
        manifest_static_authorities = (
            raw_request_closure_build.static_authorities
            if raw_request_closure_build is not None
            else ()
        )
        raw_manifest_authority = (
            self._require_raw_request_manifest_authority(
                manifest_stats_authority,
                manifest_static_authorities,
            )
            if raw_request_capture_active
            else None
        )
        observed_success_snapshots = tuple(
            source_result.get("raw_request_capture_snapshot")
            for source_result in source_results or []
            if source_result.get("raw_request_capture_snapshot") is not None
        )
        if not raw_request_capture_active and (
            observed_success_snapshots or failure_raw_request_capture_snapshots
        ):
            raise ParserInputCaptureIntegrityError(
                "raw-request snapshots reached persistence without execution authority"
            )
        if raw_request_capture_active and source_results:
            if self._w2_preparation_runtime is None:
                raise ParserInputCaptureIntegrityError(
                    "Raw Authority V2 success requires an explicit W2 preparation runtime"
                )
            for source_result in source_results:
                if type(source_result.get("raw_request_capture_snapshot")) is not (
                    RawRequestCaptureSnapshotV2
                ):
                    raise ParserInputCaptureIntegrityError(
                        "raw-request success lacks an exact capture snapshot"
                    )
                if not isinstance(
                    source_result.get("receipt_binding"),
                    LogicalCallReceiptBinding,
                ):
                    raise ParserInputCaptureIntegrityError(
                        "raw-request success lacks a logical-call receipt binding"
                    )
                _source_logical_provider_parameter_authority(source_result)
        w2_admissions: list[W2SourceCallAdmissionV1] = []
        if raw_request_capture_active:
            execution = self._raw_request_execution_identity
            assert execution is not None
            admitted_scope_sha256s = {item.scope_sha256 for item in manifest_static_authorities}
            if manifest_stats_authority is not None:
                admitted_scope_sha256s.add(manifest_stats_authority.scope.scope_sha256)
            if not admitted_scope_sha256s:
                raise ParserInputCaptureIntegrityError(
                    "raw-request capture has no admitted request scope"
                )
            snapshots = (
                *cast(
                    "tuple[RawRequestCaptureSnapshotV2, ...]",
                    observed_success_snapshots,
                ),
                *failure_raw_request_capture_snapshots,
            )
            for snapshot in snapshots:
                attempts = (
                    *(item.attempt for item in snapshot.observations),
                    *(item.attempt for item in snapshot.pending_successes),
                )
                if not attempts or any(
                    attempt.source_sha != execution.source_sha
                    or attempt.run_id != execution.run_id
                    or attempt.run_attempt != execution.run_attempt
                    or attempt.chain_id != execution.chain_id
                    or attempt.lane_id != execution.lane_id
                    or attempt.scope_sha256 not in admitted_scope_sha256s
                    for attempt in attempts
                ):
                    raise ParserInputCaptureIntegrityError(
                        "raw-request snapshot differs from execution authority"
                    )
        params_digest = digest_jsonable(chunk_params or [])
        metadata_less_call = chunk_params is None and entries is None
        if metadata_less_call:
            params_digest = digest_jsonable(
                [(key, frame_content_hash(df)) for key, df in sorted(raw.items())]
            )
        entries_digest = digest_jsonable(
            [getattr(entry, "endpoint_name", str(entry)) for entry in entries or []]
        )
        metadata = StagingChunkMetadata(
            run_mode=run_mode,
            lane_id=lane_id,
            pattern=pattern,
            chunk_index=chunk_index,
            params_digest=params_digest,
            entries_digest=entries_digest,
        )
        failure_only = bool(failure_raw_request_capture_snapshots) and not (
            raw or source_results or expected_staging_keys
        )
        store = None if failure_only or raw_request_terminal else self._staging_store_for(db)
        result = None
        if source_results:
            assert store is not None
            source_batches: list[StagingFrameBatch] = []
            replace_source_chunk = replace_existing_chunks or run_mode in {"daily", "monthly"}
            for source_result in source_results:
                source_frames = cast("dict[str, pl.DataFrame]", source_result["frames"])
                source_endpoint_name = str(source_result["source_endpoint_name"])
                source_params_json = str(source_result["source_params_json"])
                source_expected_keys = tuple(
                    str(key)
                    for key in cast(
                        "tuple[object, ...]",
                        source_result.get("expected_staging_keys", ()),
                    )
                )
                raw_receipt_binding = source_result.get("receipt_binding")
                receipt_binding: LogicalCallReceiptBinding | None
                if raw_receipt_binding is None:
                    receipt_binding = None
                elif isinstance(raw_receipt_binding, LogicalCallReceiptBinding):
                    receipt_binding = raw_receipt_binding
                else:
                    raise ParserInputCaptureIntegrityError(
                        "staging source result has an invalid logical-call receipt binding"
                    )
                raw_route_mapping = source_result.get("result_route_ids_by_staging_key", ())
                if not isinstance(raw_route_mapping, tuple) or any(
                    not isinstance(pair, tuple)
                    or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or not isinstance(pair[1], str)
                    for pair in raw_route_mapping
                ):
                    raise ParserInputCaptureIntegrityError(
                        "staging source result has invalid result-route metadata"
                    )
                route_mapping = cast(
                    "tuple[tuple[str, str], ...]",
                    raw_route_mapping,
                )
                if receipt_binding is not None:
                    try:
                        logical_params = json.loads(source_params_json)
                    except json.JSONDecodeError as exc:
                        raise ParserInputCaptureIntegrityError(
                            "receipt-bound staging source parameters are invalid JSON"
                        ) from exc
                    if not isinstance(logical_params, dict) or (
                        canonical_parameters_sha256(logical_params)
                        != receipt_binding.logical_parameters_sha256
                    ):
                        raise ParserInputCaptureIntegrityError(
                            "staging source parameters do not match the logical-call receipt"
                        )
                source_batches.append(
                    StagingFrameBatch(
                        frames=source_frames,
                        metadata=StagingChunkMetadata(
                            run_mode=run_mode,
                            lane_id=lane_id,
                            pattern=pattern,
                            chunk_index=chunk_index,
                            params_digest=params_digest,
                            entries_digest=entries_digest,
                            source_endpoint_name=source_endpoint_name,
                            source_params_digest=digest_jsonable(source_params_json),
                        ),
                        expected_staging_keys=source_expected_keys,
                        dedupe_materialized=False
                        if dedupe_materialized is None
                        else dedupe_materialized,
                        replace_existing_chunk=replace_source_chunk,
                        receipt_binding=receipt_binding,
                        result_route_ids_by_staging_key=route_mapping,
                        successor_generation_sha256=(
                            self._successor_transaction.generation_identity_sha256
                            if self._successor_transaction is not None
                            else None
                        ),
                    )
                )
            result = store.persist_frame_batches(source_batches, materialize=materialize)
        elif not failure_raw_request_capture_snapshots and not raw_request_terminal:
            assert store is not None
            result = store.persist_frames(
                raw,
                metadata=metadata,
                expected_staging_keys=expected_staging_keys,
                materialize=materialize,
                dedupe_materialized=metadata_less_call
                if dedupe_materialized is None
                else dedupe_materialized,
                replace_existing_chunk=replace_existing_chunks,
            )
        if result is not None:
            self._record_successor_replacements(result.replacement_attestations)

        if raw_request_capture_active:
            from nbadb.contracts.raw_request_finalization import (
                finalize_raw_request_capture,
                materialize_raw_request_failure_snapshot,
                materialize_raw_request_incomplete_success_snapshot,
            )
            from nbadb.orchestrate.public_value_authority_store import (
                PublicValueAuthorityStore,
            )
            from nbadb.orchestrate.raw_request_store import RawRequestAuthorityStore
            from nbadb.orchestrate.w2_operation_coordinator import coordinate_w2_source_call
            from nbadb.orchestrate.w2_operation_store import W2OperationStore

            raw_store = RawRequestAuthorityStore(db.duckdb)
            manifest_receipts: list[RawRequestAuthorityPersistenceReceiptV2] = []
            for source_result in source_results or []:
                assert store is not None
                binding = cast(
                    "LogicalCallReceiptBinding",
                    source_result["receipt_binding"],
                )
                snapshot = cast(
                    "RawRequestCaptureSnapshotV2",
                    source_result["raw_request_capture_snapshot"],
                )
                plan_live_snapshot_at = source_result.get("plan_live_snapshot_at")
                if plan_live_snapshot_at is not None and (
                    type(plan_live_snapshot_at) is not datetime
                    or plan_live_snapshot_at.tzinfo is None
                    or plan_live_snapshot_at.utcoffset() is None
                ):
                    raise ParserInputCaptureIntegrityError(
                        "raw-request source result has an invalid sealed-plan snapshot time"
                    )
                snapshot = self._bind_raw_request_snapshot_to_logical_call(
                    snapshot,
                    binding,
                    source_result.get("pending_request_observations"),
                )
                committed = store.committed_logical_call_receipts(binding)
                (
                    parameter_binding,
                    expected_parameter_binding_sha256,
                ) = _source_logical_provider_parameter_authority(source_result)
                if snapshot.issues:
                    bundle = materialize_raw_request_incomplete_success_snapshot(
                        snapshot,
                        binding,
                        committed,
                        logical_provider_parameter_binding=parameter_binding,
                        expected_logical_provider_parameter_binding_sha256=(
                            expected_parameter_binding_sha256
                        ),
                    )
                else:
                    bundle = finalize_raw_request_capture(
                        snapshot,
                        binding,
                        committed,
                        logical_provider_parameter_binding=parameter_binding,
                        expected_logical_provider_parameter_binding_sha256=(
                            expected_parameter_binding_sha256
                        ),
                        plan_live_snapshot_at=plan_live_snapshot_at,
                    )
                raw_persistence_receipt = raw_store.persist_bundle(bundle)
                manifest_receipts.append(raw_persistence_receipt)
                if snapshot.issues:
                    # A result-authority-pending unknown response is durable Raw V2
                    # evidence, but it has no selected-terminal observation and
                    # therefore cannot enter W2. The committed request-closure join
                    # below records its typed incomplete disposition instead.
                    continue
                readbacks = tuple(
                    store.committed_staging_frame_readback(receipt) for receipt in committed
                )
                runtime = self._w2_preparation_runtime
                assert runtime is not None
                candidate = runtime.prepare(
                    logical_call_binding=binding,
                    raw_authority_persistence_receipt=raw_persistence_receipt,
                    expected_raw_authority_persistence_receipt_sha256=(
                        raw_persistence_receipt.receipt_sha256
                    ),
                    raw_bundle=bundle,
                    expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
                    committed_staging_readbacks=readbacks,
                    expected_committed_staging_readback_sha256s=tuple(
                        item.readback_receipt_sha256 for item in readbacks
                    ),
                    recorded_static_attempts=source_result.get(
                        "recorded_static_attempts",
                        (),
                    ),
                    live_plan_bindings=source_result.get("live_plan_bindings", ()),
                )
                w2_admissions.append(
                    coordinate_w2_source_call(
                        candidate,
                        public_value_store=PublicValueAuthorityStore(db.duckdb),
                        operation_store=W2OperationStore(db.duckdb),
                    )
                )
            for snapshot in failure_raw_request_capture_snapshots:
                bundle = materialize_raw_request_failure_snapshot(snapshot)
                manifest_receipts.append(raw_store.persist_bundle(bundle))
            if raw_manifest_authority is None:
                raise ParserInputCaptureIntegrityError(
                    "raw-request persistence lost its manifest authority"
                )
            if manifest_receipts or raw_request_terminal:
                self._raw_request_authority_manifest = raw_store.advance_manifest(
                    raw_manifest_authority,
                    tuple(manifest_receipts),
                    terminal=raw_request_terminal,
                )
            for receipt in manifest_receipts:
                self._record_raw_request_persistence_receipt(receipt)
        if request_closure_authority is not None and source_results:
            assert store is not None
            self._record_committed_request_closure(
                store,
                source_results,
                request_closure_authority,
            )
        elif request_closure_authority is not None and not (failure_raw_request_capture_snapshots):
            if not source_results:
                raise ParserInputCaptureIntegrityError(
                    "request closure persistence lacks source-call evidence"
                )
        if self._capture_session is not None and source_results:
            for source_result in source_results:
                completed_binding = source_result.get("receipt_binding")
                if not isinstance(completed_binding, LogicalCallReceiptBinding):
                    raise ParserInputCaptureIntegrityError(
                        "capture-required durable staging success lacks a logical-call receipt"
                    )
                self._capture_session.record_completed(completed_binding)
        if result is not None:
            logger.info(
                "persisted {} staging chunk tables to DuckDB ({} rows)",
                result.staging_tables,
                result.rows_persisted,
            )
        elif failure_raw_request_capture_snapshots:
            logger.info(
                "persisted {} failed raw-request snapshot bundle(s)",
                len(failure_raw_request_capture_snapshots),
            )
        return tuple(w2_admissions)

    def _record_committed_request_closure(
        self,
        store: StagingBatchStore,
        source_results: list[dict[str, object]],
        authority: RequestClosureExecutionAuthority,
    ) -> None:
        """Join captured responses to exact read-after-commit staging receipts."""

        assured_physical_routes = {
            alias.staging_route_id for alias in authority.staging_route_aliases
        }
        for source_result in source_results:
            binding = source_result.get("receipt_binding")
            pending_items = source_result.get("pending_request_observations")
            if not isinstance(binding, LogicalCallReceiptBinding):
                raise ParserInputCaptureIntegrityError(
                    "request closure source result lacks typed pending receipt evidence"
                )
            if pending_items == ():
                if set(binding.result_route_ids).isdisjoint(assured_physical_routes):
                    continue
                raise ParserInputCaptureIntegrityError(
                    "assured staging source result omitted its pending request observation"
                )
            if not isinstance(pending_items, tuple) or any(
                not isinstance(item, PendingRequestObservation) for item in pending_items
            ):
                raise ParserInputCaptureIntegrityError(
                    "request closure source result lacks typed pending receipt evidence"
                )
            committed = store.committed_logical_call_receipts(binding)
            typed_pending_items = cast("tuple[PendingRequestObservation, ...]", pending_items)
            for pending in typed_pending_items:
                projected = bind_or_classify_committed_request_observation(
                    pending,
                    authority,
                    binding,
                    committed,
                )
                provider_request_sha256 = projected.provider_request_sha256
                if isinstance(projected, RequestObservation):
                    prior = self._request_closure_observations.get(provider_request_sha256)
                    if prior is not None and prior != projected:
                        raise ParserInputCaptureIntegrityError(
                            "request closure provider unit changed after commit"
                        )
                    if provider_request_sha256 in self._request_closure_incomplete:
                        raise ParserInputCaptureIntegrityError(
                            "request closure provider unit has conflicting outcomes"
                        )
                    self._request_closure_observations[provider_request_sha256] = projected
                else:
                    prior_incomplete = self._request_closure_incomplete.get(provider_request_sha256)
                    if prior_incomplete is not None and prior_incomplete != projected:
                        raise ParserInputCaptureIntegrityError(
                            "incomplete request closure evidence changed after commit"
                        )
                    if provider_request_sha256 in self._request_closure_observations:
                        raise ParserInputCaptureIntegrityError(
                            "request closure provider unit has conflicting outcomes"
                        )
                    self._request_closure_incomplete[provider_request_sha256] = projected

    def _record_successor_replacements(
        self,
        attestations: tuple[SourceScopeReplacementAttestation, ...],
    ) -> None:
        transaction = self._successor_transaction
        if transaction is None:
            if attestations:
                raise SuccessorUpdateContractError(
                    "successor staging receipts were produced without a successor transaction"
                )
            return
        plan = self._successor_execution_plan
        if plan is None:
            raise SuccessorUpdateContractError(
                "successor replacements require a validated execution plan"
            )
        receipts = successor_receipts_from_replacement_attestations(
            transaction=transaction,
            execution_plan=plan,
            attestations=attestations,
            active_dispatch_identity_sha256=(
                None
                if self._active_successor_dispatch is None
                else self._active_successor_dispatch.identity_sha256
            ),
        )
        for receipt in receipts:
            existing = self._successor_delta_receipts.get(receipt.requested_scope_sha256)
            if existing is not None and existing != receipt:
                raise SuccessorUpdateContractError(
                    "successor route replacement receipt changed during replay"
                )
            self._successor_delta_receipts[receipt.requested_scope_sha256] = receipt

    def _persist_discovery_capture_completion(
        self,
        completion: DiscoveryCaptureCompletion,
        *,
        run_mode: str,
    ) -> None:
        """Persist one discovery response before completing its private receipt."""

        if not isinstance(completion, DiscoveryCaptureCompletion):
            raise ParserInputCaptureIntegrityError(
                "discovery capture completion has an invalid type"
            )
        db = self._db
        if db is None:
            raise ParserInputCaptureIntegrityError(
                "discovery capture completion has no initialized durable database"
            )
        entries = get_by_endpoint(completion.endpoint_name)
        if len(entries) != 1:
            raise ParserInputCaptureIntegrityError(
                "discovery capture completion must resolve to exactly one staging route"
            )
        entry = entries[0]
        route_id = f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
        binding = completion.receipt_binding
        if binding.result_route_ids != (route_id,):
            raise ParserInputCaptureIntegrityError(
                "discovery capture completion routes differ from staging authority"
            )
        params = completion.parameters
        source_params_json = json.dumps(
            params,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        frames = {entry.staging_key: completion.frame}
        self._persist_staging_to_duckdb(
            db,
            frames,
            run_mode=run_mode,
            lane_id=(
                f"{run_mode}.discovery.{entry.endpoint_name}."
                f"{completion.scope_key.logical_parameters_sha256[:16]}"
            ),
            pattern=entry.param_pattern,
            chunk_index=0,
            chunk_params=[params],
            entries=[entry],
            expected_staging_keys=[entry.staging_key],
            source_results=[
                {
                    "frames": frames,
                    "source_endpoint_name": entry.endpoint_name,
                    "source_params_json": source_params_json,
                    "expected_staging_keys": (entry.staging_key,),
                    "receipt_binding": binding,
                    "result_route_ids_by_staging_key": ((entry.staging_key, route_id),),
                }
            ],
            materialize=False,
        )

    def _persist_discovery_game_log(
        self,
        db: DBManager,
        game_log_df: pl.DataFrame,
        *,
        run_mode: str,
        materialize: bool = False,
    ) -> None:
        if game_log_df.is_empty():
            return
        self._persist_staging_to_duckdb(
            db,
            {"stg_league_game_log": game_log_df},
            run_mode=run_mode,
            lane_id=f"{run_mode}.discovery.stg_league_game_log",
            pattern="discovery",
            chunk_index=0,
            chunk_params=[
                {
                    "staging_key": "stg_league_game_log",
                    "content_hash": frame_content_hash(game_log_df),
                }
            ],
            entries=[],
            expected_staging_keys=["stg_league_game_log"],
            dedupe_materialized=True,
            materialize=materialize,
        )

    def _materialize_staging_batches(
        self,
        db: DBManager,
        *,
        endpoints: list[str] | None = None,
        patterns: list[str] | None = None,
    ) -> int:
        keys: list[str] | None = None
        if endpoints is not None or patterns is not None:
            ep_set = set(endpoints) if endpoints else None
            pat_set = set(patterns) if patterns else None
            keys = [
                entry.staging_key
                for entry in STAGING_MAP
                if (ep_set is None or entry.endpoint_name in ep_set)
                and (pat_set is None or entry.param_pattern in pat_set)
            ]
        return self._staging_store_for(db).materialize(keys)

    def _should_reload_persisted_staging(
        self,
        outcome: ExtractionOutcome,
        *,
        runner: ExtractorRunner,
        journal: PipelineJournal,
    ) -> bool:
        """Return ``True`` only for skip-based recovery-safe extraction outcomes.

        ``stg_league_game_log`` is discovery-seeded outside the journal-aware
        extraction path, so it may be the only in-memory table even when a prior
        run already persisted the full staging snapshot. Reloading DuckDB staging
        is only safe when the current run resumed prior completed work, all
        scheduled extraction calls were journal-skipped, and no extractor or
        pattern-level failures occurred in this run.
        """
        non_empty_keys = {key for key, df in outcome.raw.items() if not df.is_empty()}
        discovery_only = not non_empty_keys or non_empty_keys == {"stg_league_game_log"}
        if not discovery_only:
            return False
        if not journal.has_done_entries():
            return False
        if runner.planned_calls <= 0:
            return False
        if runner.skipped_due_to_journal != runner.planned_calls:
            return False
        return runner.failed_current_run <= 0 and outcome.pattern_failures <= 0

    def close(self) -> PrivateGenerationIdentity | IncompleteCaptureIdentity | None:
        """Close DB and capture writers without promoting incomplete capture state."""

        try:
            if self._db is not None:
                self._db.close()
        finally:
            self._db = None
            self._journal = None
            self._staging_batch_store = None
            self._staging_batch_store_connection = None
            capture_identity = self._close_capture_session()
        return capture_identity

    # ── shared discovery (QUAL-006) ───────────────────────────

    async def _discover_entities(
        self,
        discovery: _DiscoveryService,
        seasons: list[str],
        bound_log: _BoundLogger,
        *,
        season_types: list[str] | None = None,
        include_historical_players: bool = False,
        include_games: bool = True,
        include_players: bool = True,
        include_teams: bool = True,
        include_dates: bool = True,
        require_complete: bool = False,
        require_complete_games: bool = False,
        refresh_mutable_entities: bool = False,
    ) -> tuple[list[str], list[int], list[int], list[str], pl.DataFrame]:
        """Discover game/player/team IDs and game dates in parallel.

        Shared by run_init, run_monthly, and any future run mode that
        needs all entity types.  Returns:
            (game_ids, player_ids, team_ids, game_dates, game_log_df)

        When *include_historical_players* is True (used by run_init),
        all players are discovered (active + retired). When
        *refresh_mutable_entities* is True and the active season is in scope,
        game and player caches are bypassed so monthly refreshes cannot freeze a
        mid-season inventory. *require_complete_games* applies the game coverage
        gate without requiring non-empty player and team discovery results.
        """
        import polars as pl

        pp = self._progress
        artifacts = self._discovery_artifacts()
        resolved_season_types = tuple(season_types or ["Regular Season"])
        requested_game_combos = frozenset(
            (season, season_type) for season in seasons for season_type in resolved_season_types
        )
        refresh_current_scope = refresh_mutable_entities and current_season() in seasons

        discovery_tasks: list[Awaitable[object]] = []
        game_index: int | None = None
        player_index: int | None = None
        team_index: int | None = None

        if include_games:
            game_scope = DiscoveryArtifactScope(
                kind="league_game_log",
                seasons=tuple(seasons),
                season_types=resolved_season_types,
            )
            cached_game_log = (
                None
                if refresh_current_scope or self._capture_session is not None
                else artifacts.load_game_log_frame(game_scope)
            )
            if cached_game_log is not None:
                game_ids = (
                    cached_game_log.get_column("game_id").unique().sort().to_list()
                    if not cached_game_log.is_empty() and "game_id" in cached_game_log.columns
                    else []
                )
                game_log_df = cached_game_log
                if pp is not None:
                    pp.log_discovery("games", len(game_ids))
                if include_dates:
                    game_dates = (
                        game_log_df.get_column("game_date").cast(pl.Utf8).unique().sort().to_list()
                        if "game_date" in game_log_df.columns
                        else []
                    )
                    if pp is not None:
                        pp.log_discovery("dates", len(game_dates))
                else:
                    game_dates = []
            else:
                game_index = len(discovery_tasks)
                discovery_tasks.append(
                    discovery.discover_game_ids_result(
                        seasons,
                        on_progress=pp,
                        season_types=season_types,
                    )
                )
                game_ids = []
                game_log_df = pl.DataFrame()
                game_dates = []
        else:
            game_ids = []
            game_log_df = pl.DataFrame()
            game_dates = []

        if include_players:
            player_scope = DiscoveryArtifactScope(
                kind="player_ids_all" if include_historical_players else "player_ids_active",
                seasons=tuple(seasons),
                season_types=(),
                variant="historical" if include_historical_players else "active",
            )
            cached_player_ids = (
                []
                if refresh_current_scope or self._capture_session is not None
                else artifacts.load_ids(player_scope)
            )
            if not cached_player_ids and include_historical_players and len(seasons) > 1:
                season_cached_player_ids = artifacts.load_ids_for_seasons(
                    kind="player_ids_all",
                    seasons=tuple(seasons),
                    variant="historical",
                )
                if season_cached_player_ids is not None:
                    cached_player_ids = season_cached_player_ids
                    artifacts.upsert_ids(
                        player_scope,
                        cached_player_ids,
                        provenance="per-season-discovery-cache",
                    )
            if cached_player_ids:
                player_ids = _apply_player_shard(cached_player_ids)
                if pp is not None:
                    pp.log_discovery("players", len(player_ids))
            else:
                player_index = len(discovery_tasks)
                single_season = (
                    seasons[0] if include_historical_players and len(seasons) == 1 else None
                )
                discovery_tasks.append(
                    discovery.discover_all_player_ids(season=single_season)
                    if include_historical_players
                    else discovery.discover_player_ids()
                )
                player_ids = []
        else:
            player_ids = []

        if include_teams:
            team_scope = DiscoveryArtifactScope(kind="team_ids", seasons=tuple(seasons))
            cached_team_ids = (
                [] if self._capture_session is not None else artifacts.load_ids(team_scope)
            )
            if cached_team_ids:
                team_ids = cached_team_ids
                if pp is not None:
                    pp.log_discovery("teams", len(team_ids))
            else:
                team_index = len(discovery_tasks)
                discovery_tasks.append(discovery.discover_team_ids())
                team_ids = []
        else:
            team_ids = []

        results = (
            await asyncio.gather(*discovery_tasks, return_exceptions=True)
            if discovery_tasks
            else []
        )

        _game_result = results[game_index] if game_index is not None else None
        _player_result = results[player_index] if player_index is not None else None
        _team_result = results[team_index] if team_index is not None else None

        if isinstance(_game_result, Exception):
            bound_log.warning("discover_game_ids failed: {}", type(_game_result).__name__)
            if (require_complete or require_complete_games) and include_games:
                raise InitDiscoveryCoverageError(
                    [f"discover_game_ids failed: {type(_game_result).__name__}"]
                )
            game_ids = []
            game_log_df = pl.DataFrame()
        elif _game_result is None:
            if not include_games:
                game_ids = []
                game_log_df = pl.DataFrame()
        else:
            game_discovery_result = _game_result
            assert isinstance(game_discovery_result, GameDiscoveryResult)
            if require_complete or require_complete_games:
                self._require_complete_game_discovery(
                    game_discovery_result,
                    requested_combos=requested_game_combos,
                )
            game_ids = game_discovery_result.game_ids
            game_log_df = game_discovery_result.raw
            persistable_combos = (
                requested_game_combos
                & game_discovery_result.requested_combos
                & game_discovery_result.covered_combos
            )
            persistable_frames = {
                combo: frame
                for combo, frame in game_discovery_result.frames_by_combo.items()
                if combo in persistable_combos
            }
            runtime_frames = [persistable_frames[combo] for combo in sorted(persistable_frames)]
            if runtime_frames:
                game_log_df = (
                    runtime_frames[0].clone()
                    if len(runtime_frames) == 1
                    else pl.concat(runtime_frames, how="diagonal_relaxed")
                )
                game_ids = sorted(
                    {
                        str(value)
                        for value in game_log_df.get_column("game_id").drop_nulls().to_list()
                    }
                )
            else:
                game_ids = []
                game_log_df = pl.DataFrame()
            aggregate_complete = (
                bool(requested_game_combos)
                and game_discovery_result.requested_combos == requested_game_combos
                and requested_game_combos <= game_discovery_result.covered_combos
                and requested_game_combos == frozenset(persistable_frames)
            )
            artifacts.upsert_game_log_combo_frames(
                persistable_frames,
                provenance="discovery" if aggregate_complete else "partial-discovery",
            )
            if aggregate_complete:
                aggregate_frames = [
                    persistable_frames[combo] for combo in sorted(requested_game_combos)
                ]
                aggregate_game_log = (
                    aggregate_frames[0].clone()
                    if len(aggregate_frames) == 1
                    else pl.concat(aggregate_frames, how="diagonal_relaxed")
                )
                artifacts.upsert_frame(
                    DiscoveryArtifactScope(
                        kind="league_game_log",
                        seasons=tuple(seasons),
                        season_types=resolved_season_types,
                    ),
                    aggregate_game_log,
                    provenance="discovery",
                )
            else:
                logger.warning(
                    (
                        "persisting {} covered game discovery combos individually "
                        "and skipping aggregate cache for requested scope {}"
                    ),
                    len(persistable_frames),
                    sorted(game_discovery_result.requested_combos),
                )
            if pp is not None:
                pp.log_discovery("games", len(game_ids))

        if isinstance(_player_result, Exception):
            bound_log.warning("discover_player_ids failed: {}", type(_player_result).__name__)
            if require_complete and include_players:
                raise InitDiscoveryCoverageError(
                    [f"discover_player_ids failed: {type(_player_result).__name__}"]
                )
            player_ids = []
        elif _player_result is None:
            if not include_players:
                player_ids = []
        else:
            player_ids = cast("list[int]", _player_result)
            artifacts.upsert_ids(
                DiscoveryArtifactScope(
                    kind="player_ids_all" if include_historical_players else "player_ids_active",
                    seasons=tuple(seasons),
                    season_types=(),
                    variant="historical" if include_historical_players else "active",
                ),
                player_ids,
                provenance="discovery",
            )
            player_ids = _apply_player_shard(player_ids)
            if require_complete and include_players and not player_ids:
                raise InitDiscoveryCoverageError(["player discovery returned no ids"])
            if pp is not None:
                pp.log_discovery("players", len(player_ids))

        if isinstance(_team_result, Exception):
            bound_log.warning("discover_team_ids failed: {}", type(_team_result).__name__)
            if require_complete and include_teams:
                raise InitDiscoveryCoverageError(
                    [f"discover_team_ids failed: {type(_team_result).__name__}"]
                )
            team_ids = []
        elif _team_result is None:
            if not include_teams:
                team_ids = []
        else:
            team_ids = cast("list[int]", _team_result)
            artifacts.upsert_ids(
                DiscoveryArtifactScope(kind="team_ids", seasons=tuple(seasons)),
                team_ids,
                provenance="discovery",
            )
            if require_complete and include_teams and not team_ids:
                raise InitDiscoveryCoverageError(["team discovery returned no ids"])
            if pp is not None:
                pp.log_discovery("teams", len(team_ids))

        if include_dates and not game_log_df.is_empty() and not game_dates:
            game_dates = await discovery.discover_game_dates(game_log_df)
            if pp is not None:
                pp.log_discovery("dates", len(game_dates))
        elif not include_dates:
            game_dates = []

        return game_ids, player_ids, team_ids, game_dates, game_log_df

    async def _extract_all_patterns(
        self,
        runner: ExtractorRunner,
        *,
        plan: list[ExtractionPlanItem] | None = None,
        seasons: list[str],
        game_ids: list[str],
        player_ids: list[int],
        team_ids: list[int],
        current_team_ids: list[int] | None = None,
        game_dates: list[str],
        player_team_season_params: list[dict[str, int | str]] | None = None,
        game_log_df: pl.DataFrame,
        include_static: bool = True,
        season_types: list[str] | None = None,
        context_measures: list[str] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        run_mode: str | None = None,
        journal: PipelineJournal | None = None,
        progress_store: ExtractionProgressStore | None = None,
        persist_results: ChunkPersistenceCallbackV1 | None = None,
        retain_in_memory: bool = True,
        request_closure_build: ProductionRequestClosureBuild | None = None,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
        request_closure_scope_gaps: tuple[RequestClosureScopeGap, ...] = (),
        request_closure_support_date: date | None = None,
        request_closure_inventory_path: Path | None = None,
    ) -> ExtractionOutcome:
        """Run all extraction patterns concurrently and return combined
        raw staging data.

        Pattern groups are independent (no cross-pattern dependencies),
        so they are dispatched via ``asyncio.gather`` (INFRA-010).
        """
        self._reject_later_derived_successor_fanout(surface="pattern extraction")
        if request_closure_build is not None:
            if type(request_closure_build) is not ProductionRequestClosureBuild:
                raise ParserInputCaptureIntegrityError(
                    "pattern extraction request-closure build is invalid"
                )
            if (
                request_closure_authority is not None
                or request_closure_scope_gaps
                or request_closure_support_date is not None
            ):
                raise ParserInputCaptureIntegrityError(
                    "pattern extraction received conflicting request-closure authorities"
                )
            request_closure_authority = request_closure_build.authority
            request_closure_scope_gaps = request_closure_build.scope_gaps
            request_closure_support_date = request_closure_build.support_date
        static_authorities = (
            request_closure_build.static_authorities if request_closure_build is not None else ()
        )
        if (
            request_closure_authority is not None
            or static_authorities
            or request_closure_scope_gaps
        ):
            if request_closure_authority is not None and not isinstance(
                request_closure_authority, RequestClosureExecutionAuthority
            ):
                raise ParserInputCaptureIntegrityError(
                    "pattern extraction request-closure authority is invalid"
                )
            if type(request_closure_scope_gaps) is not tuple or any(
                not isinstance(item, RequestClosureScopeGap) for item in request_closure_scope_gaps
            ):
                raise ParserInputCaptureIntegrityError(
                    "pattern extraction request-closure scope gaps are invalid"
                )
            if (
                persist_results is None
                or getattr(runner, "_capture_contract_factory", None) is None
            ):
                raise ParserInputCaptureIntegrityError(
                    "request closure requires capture-enabled committed staging persistence"
                )
            self._request_closure_observations.clear()
            self._request_closure_incomplete.clear()
            self._request_closure_inventory = None
        pp = self._progress

        raw: dict[str, pl.DataFrame] = {}
        if not game_log_df.is_empty():
            raw["stg_league_game_log"] = game_log_df
            if persist_results is not None and self._capture_session is None:
                persist_results(
                    {"stg_league_game_log": game_log_df},
                    run_mode=run_mode or "unknown",  # type: ignore[call-arg]
                    lane_id=f"{run_mode or 'unknown'}.discovery.stg_league_game_log",  # type: ignore[call-arg]
                    pattern="discovery",  # type: ignore[call-arg]
                    chunk_index=0,  # type: ignore[call-arg]
                    chunk_params=[
                        {
                            "staging_key": "stg_league_game_log",
                            "content_hash": frame_content_hash(game_log_df),
                        }
                    ],  # type: ignore[call-arg]
                    entries=[],  # type: ignore[call-arg]
                    expected_staging_keys=["stg_league_game_log"],  # type: ignore[call-arg]
                    dedupe_materialized=True,  # type: ignore[call-arg]
                    raw_request_closure_build=request_closure_build,  # type: ignore[call-arg]
                    materialize=False,  # type: ignore[call-arg]
                )

        if plan is None:
            plan = build_extraction_plan(
                seasons=seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                include_static=include_static,
                season_types=season_types,
                context_measures=context_measures,
            )
        for item in plan:
            direct_dependents = sorted(
                entry.endpoint_name
                for entry in item.entries
                if entry.endpoint_name in CUME_FOUNDATION_BY_DEPENDENT_ENDPOINT
            )
            if direct_dependents:
                raise CumeWorkloadContractError(
                    "cumulative-stat dependents cannot bypass their paired foundation: "
                    + ", ".join(direct_dependents)
                )

        if self._raw_request_execution_identity is not None:
            if (
                request_closure_authority is None and not static_authorities
            ) or request_closure_scope_gaps:
                raise ParserInputCaptureIntegrityError(
                    "public raw-request capture requires a gap-free exact request closure"
                )
            self._require_raw_request_manifest_authority(
                request_closure_authority,
                static_authorities,
            )
            if (
                persist_results is None
                or getattr(runner, "_capture_contract_factory", None) is None
            ):
                raise ParserInputCaptureIntegrityError(
                    "public raw-request capture requires private capture and committed persistence"
                )
            if any(item.cume_dependency is not None for item in plan):
                raise ParserInputCaptureIntegrityError(
                    "public raw-request capture does not yet admit derived cumulative workloads"
                )
            from nbadb.orchestrate.raw_request_context import (
                build_ordinary_raw_request_context_factory,
            )

            raw_context_factory = build_ordinary_raw_request_context_factory(
                request_closure_authority,
                static_authorities,
                self._raw_request_execution_identity,
            )
            planned_endpoint_names = {
                entry.endpoint_name for item in plan for entry in item.entries
            }
            foreign_static_endpoints = sorted(
                {item.endpoint_name for item in static_authorities} - planned_endpoint_names
            )
            if foreign_static_endpoints:
                raise ParserInputCaptureIntegrityError(
                    "public raw-request static authority is outside the execution plan: "
                    + ",".join(foreign_static_endpoints)
                )
            # Compile every planned call before the first provider request. Static
            # calls bind their exact fixed roots and never inherit stats parameters.
            for item in plan:
                endpoint_names = sorted({entry.endpoint_name for entry in item.entries})
                for endpoint_name in endpoint_names:
                    for params in item.params:
                        raw_context_factory(endpoint_name, dict(params))
            runner.configure_raw_request_capture_context_factory(raw_context_factory)

        # Compute total extraction tasks for the progress bar
        total_tasks = sum(item.task_count for item in plan)
        pattern_failures = 0
        failed_calls = 0
        extraction_errors: list[str] = []
        if pp is not None:
            pp.start_phase("Extraction", total=total_tasks)

        # Run a single pattern group
        def _journal_items_for_plan_item(item: ExtractionPlanItem) -> set[tuple[str, str]]:
            return {
                (entry.endpoint_name, json.dumps(params, sort_keys=True))
                for entry in item.entries
                for params in item.params
            }

        async def _run_one(
            idx: int,
            item: ExtractionPlanItem,
        ) -> PatternExtractionResult:
            label = item.label
            pattern = item.pattern
            entries = item.entries
            params = item.params
            n_tasks = item.task_count
            lane_key = (
                progress_store.slice_key(run_mode, item)
                if progress_store is not None and run_mode is not None
                else None
            )
            progress_store_local = progress_store
            if (
                lane_key is not None
                and progress_store_local is not None
                and progress_store_local.is_complete(lane_key)
                and item.cume_dependency is None
            ):
                journal_items = _journal_items_for_plan_item(item)
                done_items = (
                    journal.was_extracted_batch(sorted(journal_items))
                    if journal is not None
                    else set()
                )
                if journal_items and done_items == journal_items:
                    logger.info("skipping completed extraction slice: {}", label)
                    return PatternExtractionResult(frames={}, eligible_calls=0)
                logger.warning(
                    "ignoring stale extraction progress marker for {}: "
                    "{} of {} journal entries are complete",
                    label,
                    len(done_items),
                    len(journal_items),
                )
            logger.info("Step {}/{}: {} ({} tasks)", idx, len(plan), label, n_tasks)
            if pp is not None:
                pp.start_pattern(f"{label} ({n_tasks:,})", total=n_tasks)
            started_at = datetime.now(UTC)
            if lane_key is not None and progress_store_local is not None:
                progress_store_local.mark_started(lane_key, task_count=n_tasks)
            result_raw: dict[str, pl.DataFrame]
            result: PatternExtractionResult
            chunk_persist_results = persist_results
            lane_id = lane_key.slug if lane_key is not None else label

            def _make_persist_callback(
                call_entries: list[StagingEntry],
                *,
                source_sink: list[dict[str, object]] | None = None,
            ) -> ChunkPersistenceCallbackV1:
                def _persist_with_lane_metadata(
                    frames: dict[str, pl.DataFrame],
                    **metadata: object,
                ) -> ChunkPersistenceAdmissionsV1 | None:
                    source_results = cast(
                        "list[dict[str, object]] | None",
                        metadata.get("source_results"),
                    )
                    raw_failure_snapshots = metadata.get(
                        "failure_raw_request_capture_snapshots",
                        (),
                    )
                    from nbadb.extract.raw_request_capture import RawRequestCaptureSnapshotV2

                    if type(raw_failure_snapshots) is not tuple or any(
                        type(snapshot) is not RawRequestCaptureSnapshotV2
                        for snapshot in raw_failure_snapshots
                    ):
                        raise ParserInputCaptureIntegrityError(
                            "chunk callback has invalid failed raw-request snapshots"
                        )
                    if source_sink is not None:
                        if source_results is None or any(
                            not isinstance(source_result, dict) for source_result in source_results
                        ):
                            raise CumeWorkloadContractError(
                                "cume foundation callback lacks exact source-call evidence"
                            )
                        source_sink.extend(source_results)
                    if chunk_persist_results is None:
                        return None
                    raw_chunk_index = metadata.get("chunk_index")
                    chunk_index = raw_chunk_index if isinstance(raw_chunk_index, int) else 0
                    persist_metadata: dict[str, object] = {
                        "run_mode": run_mode or "unknown",
                        "lane_id": lane_id,
                        "pattern": pattern,
                        "chunk_index": chunk_index,
                        "chunk_params": cast(
                            "list[dict] | None",
                            metadata.get("chunk_params"),
                        ),
                        "entries": call_entries,
                        "expected_staging_keys": cast(
                            "list[str] | None",
                            metadata.get("expected_staging_keys"),
                        ),
                        "materialize": False,
                    }
                    call_request_closure_authority = None
                    if request_closure_authority is not None:
                        physical_route_ids = {
                            f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
                            for entry in call_entries
                        }
                        closure_physical_route_ids = {
                            alias.staging_route_id
                            for alias in request_closure_authority.staging_route_aliases
                        }
                        if physical_route_ids & closure_physical_route_ids:
                            call_request_closure_authority = request_closure_authority
                    if call_request_closure_authority is not None:
                        persist_metadata["request_closure_authority"] = (
                            call_request_closure_authority
                        )
                    if source_results is not None:
                        persist_metadata["source_results"] = source_results
                    if raw_failure_snapshots:
                        persist_metadata["failure_raw_request_capture_snapshots"] = (
                            raw_failure_snapshots
                        )
                    if request_closure_build is not None:
                        persist_metadata["raw_request_closure_build"] = request_closure_build
                    return chunk_persist_results(frames, **persist_metadata)

                return _persist_with_lane_metadata

            async def _invoke(
                call_params: list[dict],
                call_entries: list[StagingEntry],
                *,
                source_sink: list[dict[str, object]] | None = None,
            ) -> PatternExtractionResult:
                callback = (
                    _make_persist_callback(call_entries, source_sink=source_sink)
                    if chunk_persist_results is not None or source_sink is not None
                    else None
                )
                try:
                    signature_target = runner.run_pattern_result
                    side_effect = getattr(signature_target, "side_effect", None)
                    if callable(side_effect):
                        signature_target = side_effect
                    runner_parameters = inspect.signature(signature_target).parameters
                    supports_retention = "retain_frames" in runner_parameters
                except (TypeError, ValueError):
                    supports_retention = False
                retention_kwargs = {"retain_frames": retain_in_memory} if supports_retention else {}
                run_pattern_result = cast("Any", runner.run_pattern_result)
                closure_kwargs: dict[str, RequestClosureExecutionAuthority] = {}
                support_kwargs: dict[str, date] = {}
                if request_closure_support_date is not None:
                    support_kwargs["support_date"] = request_closure_support_date
                if request_closure_authority is not None:
                    physical_route_ids = {
                        f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
                        for entry in call_entries
                    }
                    closure_physical_route_ids = {
                        alias.staging_route_id
                        for alias in request_closure_authority.staging_route_aliases
                    }
                    if physical_route_ids & closure_physical_route_ids:
                        closure_kwargs["request_closure_authority"] = request_closure_authority
                if skip_items and callback is not None:
                    return await run_pattern_result(
                        pattern,
                        call_params,
                        call_entries,
                        on_progress=pp,
                        skip_items=skip_items,
                        persist_chunk_results=callback,
                        **retention_kwargs,
                        **closure_kwargs,
                        **support_kwargs,
                    )
                if skip_items:
                    return await run_pattern_result(
                        pattern,
                        call_params,
                        call_entries,
                        on_progress=pp,
                        skip_items=skip_items,
                        **retention_kwargs,
                        **closure_kwargs,
                        **support_kwargs,
                    )
                if callback is not None:
                    return await run_pattern_result(
                        pattern,
                        call_params,
                        call_entries,
                        on_progress=pp,
                        persist_chunk_results=callback,
                        **retention_kwargs,
                        **closure_kwargs,
                        **support_kwargs,
                    )
                return await run_pattern_result(
                    pattern,
                    call_params,
                    call_entries,
                    on_progress=pp,
                    **retention_kwargs,
                    **closure_kwargs,
                    **support_kwargs,
                )

            dependency = item.cume_dependency
            if dependency is None:
                result = await _invoke(params, entries)
            else:
                foundation_sources: list[dict[str, object]] = []
                foundation_result = await _invoke(
                    params,
                    entries,
                    source_sink=foundation_sources,
                )
                if not foundation_result.is_complete:
                    result = foundation_result
                else:
                    workloads = _derive_cume_workloads(
                        item,
                        foundation_sources,
                        capture_required=(
                            getattr(runner, "_capture_contract_factory", None) is not None
                        ),
                    )
                    executable_workloads = [
                        workload
                        for workload in workloads
                        if workload.disposition is CumeWorkloadDisposition.COMPLETE
                    ]
                    if executable_workloads:
                        dependent_result = await _invoke(
                            [
                                cume_workload_execution_params(workload)
                                for workload in executable_workloads
                            ],
                            list(dependency.dependent_entries),
                        )
                        result = _combine_pattern_results(
                            foundation_result,
                            dependent_result,
                        )
                    else:
                        result = foundation_result
            result_raw = result.frames

            completed_at = datetime.now(UTC)
            row_count = result.row_count
            endpoint_families = sorted(
                {
                    endpoint_family(entry.endpoint_name, getattr(entry, "param_pattern", pattern))
                    for entry in item.coverage_entries
                }
            )
            if lane_key is not None and progress_store_local is not None:
                if result.is_complete:
                    progress_store_local.mark_complete(
                        lane_key,
                        task_count=n_tasks,
                        eligible_calls=result.eligible_calls,
                        success_count=result.success_count,
                        journal_skip_count=result.journal_skip_count,
                        retry_skip_count=result.retry_skip_count,
                        support_skip_count=result.support_skip_count,
                        failure_count=result.failure_count,
                        deferred_failure_count=result.deferred_failure_count,
                        row_count=row_count,
                        wall_time_seconds=(completed_at - started_at).total_seconds(),
                        staging_keys=sorted(result_raw),
                        endpoint_families=endpoint_families,
                    )
                else:
                    progress_store_local.mark_failed(
                        lane_key,
                        task_count=n_tasks,
                        eligible_calls=result.eligible_calls,
                        success_count=result.success_count,
                        journal_skip_count=result.journal_skip_count,
                        retry_skip_count=result.retry_skip_count,
                        support_skip_count=result.support_skip_count,
                        failure_count=result.failure_count,
                        deferred_failure_count=result.deferred_failure_count,
                        error="; ".join(result.errors) or "incomplete extraction slice",
                    )
            if journal is not None and lane_key is not None:
                journal.record_lane_metric(
                    lane_id=lane_key.slug,
                    run_mode=run_mode or "unknown",
                    pattern=pattern,
                    endpoint_families=endpoint_families,
                    started_at=started_at,
                    completed_at=completed_at,
                    wall_time_seconds=(completed_at - started_at).total_seconds(),
                    task_count=result.eligible_calls,
                    row_count=row_count,
                    success_count=result.success_count + result.journal_skip_count,
                    failure_count=result.failure_count + result.deferred_failure_count,
                )
            return result

        # Group plan items by priority tier and run tiers sequentially.
        # Within each tier, patterns run concurrently.  This ensures
        # small/fast extractions complete before the massive game-level
        # extraction begins.
        tier_groups: dict[int, list[tuple[int, ExtractionPlanItem]]] = {}
        for i, item in enumerate(plan, 1):
            tier_groups.setdefault(item.priority, []).append((i, item))

        for tier_key in sorted(tier_groups):
            tier_items = tier_groups[tier_key]
            tier_labels = ", ".join(item.label for _, item in tier_items)
            logger.info("priority tier {}: {}", tier_key, tier_labels)

            tier_results = await asyncio.gather(
                *[_run_one(idx, item) for idx, item in tier_items],
                return_exceptions=True,
            )

            for j, result in enumerate(tier_results):
                if isinstance(result, BaseException):
                    failed_item = tier_items[j][1]
                    failed_label = failed_item.label
                    failed_task_count = failed_item.task_count
                    pattern_failures += 1
                    failed_calls += failed_task_count
                    extraction_errors.append(
                        f"{failed_label}[{failed_item.pattern}]: "
                        f"{type(result).__name__}: {result} "
                        f"(task_count={failed_task_count})"
                    )
                    if progress_store is not None and run_mode is not None:
                        lane_key = progress_store.slice_key(run_mode, failed_item)
                        progress_store.mark_failed(
                            lane_key,
                            task_count=failed_task_count,
                            error=f"{type(result).__name__}: {result}",
                        )
                        if journal is not None:
                            failed_at = datetime.now(UTC)
                            journal.record_lane_metric(
                                lane_id=lane_key.slug,
                                run_mode=run_mode,
                                pattern=failed_item.pattern,
                                endpoint_families=sorted(
                                    {
                                        endpoint_family(
                                            entry.endpoint_name,
                                            getattr(
                                                entry,
                                                "param_pattern",
                                                failed_item.pattern,
                                            ),
                                        )
                                        for entry in failed_item.coverage_entries
                                    }
                                ),
                                started_at=failed_at,
                                completed_at=failed_at,
                                wall_time_seconds=0.0,
                                task_count=failed_task_count,
                                row_count=0,
                                success_count=0,
                                failure_count=failed_task_count,
                            )
                    logger.error(
                        "pattern {} failed: {}",
                        failed_label,
                        type(result).__name__,
                    )
                    continue
                if not result.is_complete:
                    pattern_failures += 1
                    failed_calls += result.failure_count + result.deferred_failure_count
                    extraction_errors.extend(result.errors)
                if retain_in_memory:
                    raw.update(result.frames)

        if pp is not None:
            pp.complete_phase()

        if (
            request_closure_authority is not None or request_closure_scope_gaps
        ) and pattern_failures == 0:
            inventory = RequestClosureObservationInventory(
                authority=request_closure_authority,
                observations=tuple(
                    self._request_closure_observations[key]
                    for key in sorted(self._request_closure_observations)
                ),
                incomplete=tuple(
                    self._request_closure_incomplete[key]
                    for key in sorted(self._request_closure_incomplete)
                ),
                scope_gaps=request_closure_scope_gaps,
            )
            inventory_path = request_closure_inventory_path or (
                self._settings.data_dir / "request-closure-observation-inventory.json"
            )
            atomic_write_text(inventory_path, inventory.canonical_bytes.decode("utf-8"))
            if inventory_path.read_bytes() != inventory.canonical_bytes:
                raise ParserInputCaptureIntegrityError(
                    "request closure inventory changed during atomic persistence"
                )
            self._request_closure_inventory = inventory
            if inventory.incomplete:
                reasons = ",".join(item.reason_code for item in inventory.incomplete)
                raise ParserInputCaptureIntegrityError(
                    "request closure remains incomplete after committed staging: " + reasons
                )

        if (
            self._raw_request_execution_identity is not None
            and request_closure_build is not None
            and pattern_failures == 0
        ):
            if persist_results is None:
                raise ParserInputCaptureIntegrityError(
                    "raw-request terminal sealing requires committed persistence"
                )
            persist_results(
                {},
                run_mode=run_mode or "unknown",  # type: ignore[call-arg]
                lane_id=f"{run_mode or 'unknown'}.raw-request-terminal",  # type: ignore[call-arg]
                pattern="raw_request_terminal",  # type: ignore[call-arg]
                raw_request_closure_build=request_closure_build,  # type: ignore[call-arg]
                raw_request_terminal=True,  # type: ignore[call-arg]
                materialize=False,  # type: ignore[call-arg]
            )

        return ExtractionOutcome(
            raw=raw,
            pattern_failures=pattern_failures,
            failed_calls=failed_calls,
            errors=extraction_errors,
        )

    # ── run modes ──────────────────────────────────────────────

    async def run_init(
        self,
        start_season: int = 1946,
        end_season: int | None = None,
        season_types: list[str] | None = None,
    ) -> PipelineResult:
        """Run full initialization under the optional capture lifecycle."""

        return await self._run_capture_managed(
            lambda: self._run_init(start_season, end_season, season_types),
        )

    async def _run_init(
        self,
        start_season: int = 1946,
        end_season: int | None = None,
        season_types: list[str] | None = None,
    ) -> PipelineResult:
        """Full history build with resume support.

        Resume logic works automatically via the extraction journal:
        - Each extraction checks ``journal.was_extracted()``
        - If interrupted, re-running skips all successful work
        - Failed extractions are retried on the next run

        On startup, lingering ``running`` rows are recovered to replayable
        failures so interrupted work can be resumed without manual SQL repair.
        This assumes a single active writer per pipeline DB/journal.
        Completed entries are never cleared, preserving progress from prior
        partial runs (QUAL-003).

        *season_types* controls which season types are extracted.
        Defaults to the full supported season-type universe.
        """
        season_types = self._resolved_season_types(season_types)
        self._enable_ordinary_request_closure_capture()

        bound_log = cast("_BoundLogger", logger.bind(run_mode="init"))
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            pp = self._progress
            if journal.has_done_entries():
                bound_log.info("init resume: prior completed entries found, will skip those")
                if pp is not None:
                    s = journal.resume_summary()
                    pp.log_resume_context(s["done"], s["failed"], s["total_rows"])

            # -- 1. Entity discovery (parallel) --------------------
            seasons = season_range(start_season, end_season)
            discovery = self._build_discovery(
                thread_pool=runner._thread_pool,
                run_mode="init",
            )

            bound_log.info(
                "init: discovering entities for {} seasons × {} season_types",
                len(seasons),
                len(season_types),
            )
            if pp is not None:
                pp.start_phase("Discovery")
                pp.update_phase_info(f"scanning {len(seasons)} seasons...")

            entity_task = asyncio.create_task(
                self._discover_entities(
                    discovery,
                    seasons,
                    bound_log,
                    season_types=season_types,
                    include_historical_players=True,
                    require_complete=True,
                )
            )
            current_team_task = asyncio.create_task(
                self._discover_current_team_ids(discovery, seasons=seasons)
            )
            player_team_task = asyncio.create_task(
                self._discover_player_team_season_result(
                    discovery,
                    seasons=seasons,
                    season_types=season_types,
                    run_mode="init",
                )
            )
            (
                (game_ids, player_ids, team_ids, game_dates, game_log_df),
                current_team_ids,
                player_team_result,
            ) = await asyncio.gather(entity_task, current_team_task, player_team_task)
            if not current_team_ids:
                raise InitDiscoveryCoverageError(["current-team discovery returned no ids"])
            self._require_complete_player_team_discovery(player_team_result)
            player_team_season_params = self._persist_player_team_season_workloads(
                player_team_result.params,
                seasons=seasons,
                season_types=season_types,
                covered_pairs=set(player_team_result.covered_pairs),
            )

            if pp is not None:
                pp.complete_phase()

            bound_log.info(
                "discovered: {} games, {} players, {} teams, {} dates, {} player-team seasons",
                len(game_ids),
                len(player_ids),
                len(team_ids),
                len(game_dates),
                len(player_team_season_params),
            )

            # -- 2. Extract by pattern ------------------------------
            plan = build_extraction_plan(
                seasons=seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                season_types=season_types,
            )
            closure_support_date = date.today()
            request_closure = self._build_ordinary_request_closure(
                runner,
                plan,
                run_mode="init",
                support_date=closure_support_date,
                discovery_seed_requested=True,
                recurring_live_requested=False,
            )
            extraction = await self._extract_all_patterns(
                runner,
                plan=plan,
                seasons=seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                game_log_df=game_log_df,
                season_types=season_types,
                run_mode="init",
                journal=journal,
                progress_store=self._extraction_progress(),
                persist_results=lambda frames, **metadata: self._persist_staging_to_duckdb(
                    db,
                    frames,
                    **metadata,
                ),
                retain_in_memory=False,
                request_closure_build=request_closure,
            )
            raw = extraction.raw

            if extraction.pattern_failures or extraction.failed_calls or journal.get_failed():
                bound_log.error(
                    "init extraction incomplete: {} pattern failures, {} failed calls",
                    extraction.pattern_failures,
                    extraction.failed_calls,
                )
                result = self._build_result(
                    t0,
                    0,
                    0,
                    0,
                    journal=journal,
                    extra_errors=extraction.errors,
                    include_exhausted=True,
                    include_abandoned=True,
                )
                result.failed_extractions = max(
                    result.failed_extractions,
                    extraction.failed_calls or extraction.pattern_failures,
                )
                result.skipped_extractions = runner.skipped
                runner.log_latency_summary()
                return result

            self._materialize_staging_batches(db)

            # -- 2b. Phase-B warehouse load from durable staged batches ----
            bound_log.info("loading durable staged extraction batches from DuckDB")
            raw = self._load_staging_from_duckdb(db)
            bound_log.info("loaded {} staging tables from DuckDB", len(raw))

            # -- 3. Transform + Load --------------------------------
            if pp is not None:
                pp.start_phase("Transform & Load")
                pp.update_phase_info(f"{len(raw)} staging tables")
            bound_log.info("transform + load: {} staging tables", len(raw))
            tables_updated, rows_total, failed_loads = self._transform_and_load(
                db, raw, journal, mode="replace"
            )
            if pp is not None:
                pp.update_phase_info(f"{tables_updated} tables, {rows_total:,} rows loaded")
                pp.complete_phase()

            # -- 4. Summarize result --------------------------------
            # Abandon items that have exceeded the retry cap so they don't
            # block the chain from terminating.
            abandoned = journal.abandon_exhausted()

            result = self._build_result(
                t0,
                tables_updated,
                rows_total,
                failed_loads,
                journal=journal,
            )
            self._apply_extraction_outcome(result, extraction)
            result.skipped_extractions = runner.skipped
            runner.log_latency_summary()

        bound_log.info(
            "init complete: {} tables, {} rows, {:.1f}s, "
            "{} extract failures, {} abandoned, {} load failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
            abandoned,
            result.failed_loads,
        )
        journal.log_summary()
        return result

    async def run_daily(self) -> PipelineResult:
        """Run the daily update under the optional capture lifecycle."""

        if self._successor_transaction is not None:
            self._require_successor_mode(SuccessorUpdateMode.DAILY)
        return await self._run_capture_managed(self._run_daily)

    async def _run_daily(self) -> PipelineResult:
        """Incremental update focused on recent games.

        1. Extract league_game_log for current season
        2. Filter to games within ``daily_lookback_days``
        3. Run game-level extractors for those game_ids
        4. Refresh current-season endpoints across their declared season types
        5. Persist receipt-bound live source batches
        6. Transform + load the complete historical and live universe (replace)
        """
        self._reject_later_derived_successor_fanout(surface="daily discovery")
        self._enable_ordinary_request_closure_capture()
        import polars as pl

        bound_log = cast("_BoundLogger", logger.bind(run_mode="daily"))
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery(
                thread_pool=runner._thread_pool,
                run_mode="daily",
            )

            season = current_season()
            bound_log.info("daily: season={}", season)

            # -- 1. Discover recent game_ids across the full declared contract -----
            daily_season_types = list(DEFAULT_SEASON_TYPES)
            game_result = await discovery.discover_game_ids_result(
                [season],
                season_types=daily_season_types,
            )
            self._require_complete_game_discovery(
                game_result,
                requested_combos=frozenset(
                    (season, season_type) for season_type in daily_season_types
                ),
            )
            game_ids = game_result.game_ids
            game_log_df = game_result.raw

            raw: dict[str, pl.DataFrame] = {}
            if not game_log_df.is_empty():
                raw["stg_league_game_log"] = game_log_df

            # Filter to recent dates
            if not game_log_df.is_empty() and "game_date" in game_log_df.columns:
                from datetime import datetime, timedelta

                lookback = self._settings.daily_lookback_days
                cutoff = (datetime.now() - timedelta(days=lookback)).strftime("%Y-%m-%d")
                recent = game_log_df.filter(pl.col("game_date").cast(pl.Utf8) >= cutoff)
                game_ids = recent.get_column("game_id").unique().sort().to_list()
                game_dates = recent.get_column("game_date").cast(pl.Utf8).unique().sort().to_list()
            else:
                game_dates = []

            bound_log.info(
                "daily: {} recent games, {} dates",
                len(game_ids),
                len(game_dates),
            )

            # -- 2. Discover active players + teams for lightweight refresh
            player_ids = await discovery.discover_player_ids()
            team_ids = await discovery.discover_team_ids()
            current_team_ids = await self._discover_current_team_ids(
                discovery,
                seasons=[season],
                refresh=True,
            )
            player_team_result = await self._discover_player_team_season_result(
                discovery,
                seasons=[season],
                season_types=daily_season_types,
                run_mode="daily",
            )
            self._require_complete_player_team_discovery(player_team_result)
            player_team_season_params = self._persist_player_team_season_workloads(
                player_team_result.params,
                seasons=[season],
                season_types=daily_season_types,
                covered_pairs=set(player_team_result.covered_pairs),
            )
            bound_log.info(
                "daily: {} active players, {} teams, {} player-team seasons for refresh",
                len(player_ids),
                len(team_ids),
                len(player_team_season_params),
            )

            # -- 3. Game + season + date + player/team extraction
            plan = build_extraction_plan(
                seasons=[season],
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                include_static=False,
                season_types=daily_season_types,
            )
            closure_support_date = date.today()
            request_closure = self._build_ordinary_request_closure(
                runner,
                plan,
                run_mode="daily",
                support_date=closure_support_date,
                discovery_seed_requested=True,
                recurring_live_requested=True,
            )
            extraction = await self._extract_all_patterns(
                runner,
                plan=plan,
                seasons=[season],
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                game_log_df=game_log_df,
                include_static=False,
                season_types=daily_season_types,
                run_mode="daily",
                journal=journal,
                progress_store=self._extraction_progress(),
                persist_results=lambda frames, **metadata: self._persist_staging_to_duckdb(
                    db, frames, **metadata
                ),
                retain_in_memory=False,
                request_closure_build=request_closure,
            )
            raw.update(extraction.raw)
            # Keep the seeded game_log_df (update may have cleared it)
            if not game_log_df.is_empty():
                raw.setdefault("stg_league_game_log", game_log_df)

            if extraction.pattern_failures or extraction.failed_calls or journal.get_failed():
                bound_log.error(
                    "daily extraction incomplete: {} pattern failures, {} failed calls",
                    extraction.pattern_failures,
                    extraction.failed_calls,
                )
                result = self._build_result(
                    t0,
                    0,
                    0,
                    0,
                    journal=journal,
                    extra_errors=extraction.errors,
                    include_exhausted=True,
                    include_abandoned=True,
                )
                result.failed_extractions = max(
                    result.failed_extractions,
                    extraction.failed_calls or extraction.pattern_failures,
                )
                result.skipped_extractions = runner.skipped
                runner.log_latency_summary()
                return result

            live_snapshot = self._persist_recurring_live_snapshot(db, run_mode="daily")
            self._materialize_staging_batches(db)
            raw = self._load_staging_from_duckdb(db)
            bound_log.info("daily loaded {} staged tables from DuckDB", len(raw))

            # -- 3. Transform + Load --------------------------------
            tables_updated, rows_total, failed_loads = self._transform_and_load(
                db,
                raw,
                journal,
                mode="replace",
                require_complete_transforms=True,
                materialize_empty_outputs=True,
                include_live_transforms=True,
            )
            bound_log.info(
                "daily live closure: {} active games, {} provider calls",
                len(live_snapshot.game_ids),
                len(live_snapshot.source_calls),
            )

            journal.abandon_exhausted()
            result = self._build_result(
                t0,
                tables_updated,
                rows_total,
                failed_loads,
                journal=journal,
            )
            self._apply_extraction_outcome(result, extraction)
            result.skipped_extractions = runner.skipped
            runner.log_latency_summary()

        bound_log.info(
            "daily complete: {} tables, {} rows, {:.1f}s, {} extract failures, {} load failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
            result.failed_loads,
        )
        return result

    async def run_monthly(self) -> PipelineResult:
        """Run the monthly refresh under the optional capture lifecycle."""

        if self._successor_transaction is not None:
            self._require_successor_mode(SuccessorUpdateMode.MONTHLY)
        return await self._run_capture_managed(self._run_monthly)

    async def _run_monthly(self) -> PipelineResult:
        """Monthly refresh of the last 3 seasons.

        Runs all pattern types for ``recent_seasons(3)`` across the full
        supported season-type universe, persists receipt-bound live source
        batches, then transforms the complete historical and live universe.
        """
        self._reject_later_derived_successor_fanout(surface="monthly discovery")
        self._enable_ordinary_request_closure_capture()
        bound_log = cast("_BoundLogger", logger.bind(run_mode="monthly"))
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery(
                thread_pool=runner._thread_pool,
                run_mode="monthly",
            )

            seasons = recent_seasons(3)
            bound_log.info("monthly: seasons={}", seasons)

            # -- 1. Discover entities (parallel) --- uses shared helper
            monthly_season_types = list(DEFAULT_SEASON_TYPES)
            game_ids, player_ids, team_ids, game_dates, game_log_df = await self._discover_entities(
                discovery,
                seasons,
                bound_log,
                season_types=monthly_season_types,
                include_players=False,
                require_complete_games=True,
                refresh_mutable_entities=True,
            )
            player_ids = await self._discover_complete_historical_player_union(
                discovery,
                seasons=seasons,
            )
            current_team_ids = await self._discover_current_team_ids(
                discovery,
                seasons=seasons,
                refresh=True,
            )
            player_team_result = await self._discover_player_team_season_result(
                discovery,
                seasons=seasons,
                season_types=monthly_season_types,
                run_mode="monthly",
            )
            self._require_complete_player_team_discovery(player_team_result)
            player_team_season_params = self._persist_player_team_season_workloads(
                player_team_result.params,
                seasons=seasons,
                season_types=monthly_season_types,
                covered_pairs=set(player_team_result.covered_pairs),
            )

            # -- 2. Extract all patterns ----------------------------
            plan = build_extraction_plan(
                seasons=seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                season_types=monthly_season_types,
            )
            closure_support_date = date.today()
            request_closure = self._build_ordinary_request_closure(
                runner,
                plan,
                run_mode="monthly",
                support_date=closure_support_date,
                discovery_seed_requested=True,
                recurring_live_requested=True,
            )
            extraction = await self._extract_all_patterns(
                runner,
                plan=plan,
                seasons=seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                game_log_df=game_log_df,
                season_types=monthly_season_types,
                run_mode="monthly",
                journal=journal,
                progress_store=self._extraction_progress(),
                persist_results=lambda frames, **metadata: self._persist_staging_to_duckdb(
                    db, frames, **metadata
                ),
                retain_in_memory=False,
                request_closure_build=request_closure,
            )
            raw = extraction.raw

            if extraction.pattern_failures or extraction.failed_calls or journal.get_failed():
                bound_log.error(
                    "monthly extraction incomplete: {} pattern failures, {} failed calls",
                    extraction.pattern_failures,
                    extraction.failed_calls,
                )
                result = self._build_result(
                    t0,
                    0,
                    0,
                    0,
                    journal=journal,
                    extra_errors=extraction.errors,
                    include_exhausted=True,
                    include_abandoned=True,
                )
                result.failed_extractions = max(
                    result.failed_extractions,
                    extraction.failed_calls or extraction.pattern_failures,
                )
                result.skipped_extractions = runner.skipped
                runner.log_latency_summary()
                return result

            live_snapshot = self._persist_recurring_live_snapshot(db, run_mode="monthly")
            self._materialize_staging_batches(db)
            raw = self._load_staging_from_duckdb(db)
            bound_log.info("monthly loaded {} staged tables from DuckDB", len(raw))

            # -- 3. Transform + Load --------------------------------
            tables_updated, rows_total, failed_loads = self._transform_and_load(
                db,
                raw,
                journal,
                mode="replace",
                require_complete_transforms=True,
                materialize_empty_outputs=True,
                include_live_transforms=True,
            )
            bound_log.info(
                "monthly live closure: {} active games, {} provider calls",
                len(live_snapshot.game_ids),
                len(live_snapshot.source_calls),
            )

            journal.abandon_exhausted()
            result = self._build_result(
                t0,
                tables_updated,
                rows_total,
                failed_loads,
                journal=journal,
            )
            self._apply_extraction_outcome(result, extraction)
            result.skipped_extractions = runner.skipped
            runner.log_latency_summary()

        bound_log.info(
            "monthly complete: {} tables, {} rows, {:.1f}s, {} extract failures, {} load failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
            result.failed_loads,
        )
        return result

    async def run_retry(self) -> PipelineResult:
        """Run retry and gap filling under the optional capture lifecycle."""

        return await self._run_capture_managed(self._run_retry)

    async def _run_retry(self) -> PipelineResult:
        """Retries previously failed extractions.

        Does NOT discover new entities or fill gaps from newly played
        games.  Use ``run_init`` for comprehensive coverage.

        1. Read journal for failed/incomplete extractions
        2. Retry those extractions
        3. Check watermarks for missing seasons
        4. Transform + load
        """
        bound_log = cast("_BoundLogger", logger.bind(run_mode="retry"))
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery(
                thread_pool=runner._thread_pool,
                run_mode="retry",
            )

            # -- 1. Retry failed extractions ------------------------
            failed = journal.get_failed(include_exhausted=True, include_abandoned=True)
            bound_log.info(
                "retry: {} failed extractions to retry",
                len(failed),
            )

            # Group failed by pattern for batched re-extraction
            failed_by_entry: dict[str, list[dict]] = {}  # endpoint -> params
            attempted_retry_items: set[tuple[str, str]] = set()
            for endpoint, params_json, _error in failed:
                try:
                    params = json.loads(params_json)
                except (TypeError, json.JSONDecodeError) as exc:
                    quarantine_error = f"invalid_params_json:{type(exc).__name__}"
                    journal.record_failure(endpoint, params_json, quarantine_error)
                    bound_log.warning(
                        "retry: skipping malformed failed params_json for {}: {} ({})",
                        endpoint,
                        params_json,
                        quarantine_error,
                    )
                    continue
                if not isinstance(params, dict):
                    quarantine_error = f"invalid_params_json:{type(params).__name__}"
                    journal.record_failure(endpoint, params_json, quarantine_error)
                    bound_log.warning(
                        "retry: skipping non-object failed params_json for {}: {} ({})",
                        endpoint,
                        params_json,
                        quarantine_error,
                    )
                    continue
                failed_by_entry.setdefault(endpoint, []).append(params)

            # Build a lookup from endpoint_name -> StagingEntry(s)
            entries_by_ep: dict[str, list] = {}
            for entry in STAGING_MAP:
                entries_by_ep.setdefault(entry.endpoint_name, []).append(entry)

            raw: dict[str, pl.DataFrame] = {}

            for endpoint, param_list in failed_by_entry.items():
                ep_entries = entries_by_ep.get(endpoint, [])
                if not ep_entries:
                    bound_log.warning(
                        "no staging entry for failed endpoint: {}",
                        endpoint,
                    )
                    continue
                pattern = ep_entries[0].param_pattern

                def _persist_retry_chunk(
                    frames: dict[str, pl.DataFrame],
                    *,
                    _endpoint=endpoint,
                    _pattern=pattern,
                    _entries=ep_entries,
                    **metadata: object,
                ) -> ChunkPersistenceAdmissionsV1:
                    source_results = cast(
                        "list[dict[str, object]] | None",
                        metadata.get("source_results"),
                    )
                    if source_results is not None:
                        return self._persist_staging_to_duckdb(
                            db,
                            frames,
                            run_mode="retry-direct",
                            lane_id=f"retry.direct.{_endpoint}",
                            pattern=_pattern,
                            chunk_index=cast("int", metadata.get("chunk_index") or 0),
                            chunk_params=cast(
                                "list[dict] | None",
                                metadata.get("chunk_params"),
                            ),
                            entries=_entries,
                            expected_staging_keys=cast(
                                "list[str] | None",
                                metadata.get("expected_staging_keys"),
                            ),
                            source_results=source_results,
                            materialize=False,
                        )
                    return self._persist_staging_to_duckdb(
                        db,
                        frames,
                        run_mode="retry-direct",
                        lane_id=f"retry.direct.{_endpoint}",
                        pattern=_pattern,
                        chunk_index=cast("int", metadata.get("chunk_index") or 0),
                        chunk_params=cast("list[dict] | None", metadata.get("chunk_params")),
                        entries=_entries,
                        expected_staging_keys=cast(
                            "list[str] | None",
                            metadata.get("expected_staging_keys"),
                        ),
                        materialize=False,
                    )

                retry_result = await runner.run_pattern_result(
                    pattern,
                    param_list,
                    ep_entries,
                    persist_chunk_results=_persist_retry_chunk,
                )
                raw.update(retry_result.frames)
                if retry_result.is_complete:
                    for params in param_list:
                        attempted_retry_items.add((endpoint, json.dumps(params, sort_keys=True)))

            # -- 2. Gap-fill ALL patterns (not just season+game) ------
            _full_st = list(DEFAULT_SEASON_TYPES)
            seasons = season_range()

            # Discover entities for gap-filling
            game_ids, player_ids, team_ids, game_dates, game_log_df = await self._discover_entities(
                discovery, seasons, bound_log, season_types=_full_st
            )
            current_team_ids = await self._discover_current_team_ids(discovery, seasons=seasons)
            player_team_result = await self._discover_player_team_season_result(
                discovery,
                seasons=seasons,
                season_types=_full_st,
                run_mode="retry",
            )
            self._require_complete_player_team_discovery(player_team_result)
            player_team_season_params = self._persist_player_team_season_workloads(
                player_team_result.params,
                seasons=seasons,
                season_types=_full_st,
                covered_pairs=set(player_team_result.covered_pairs),
            )
            if not game_log_df.is_empty():
                raw.setdefault("stg_league_game_log", game_log_df)

            # Run all patterns — runner will skip already-extracted via journal
            extraction = await self._extract_all_patterns(
                runner,
                seasons=seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                game_log_df=game_log_df,
                season_types=_full_st,
                skip_items=attempted_retry_items,
                run_mode="retry",
                journal=journal,
                progress_store=self._extraction_progress(),
                persist_results=lambda frames, **metadata: self._persist_staging_to_duckdb(
                    db, frames, **metadata
                ),
                retain_in_memory=False,
            )
            raw.update(extraction.raw)

            self._materialize_staging_batches(db)
            raw = self._load_staging_from_duckdb(db)
            bound_log.info("retry loaded {} staged tables from DuckDB", len(raw))

            # -- 3. Transform + Load --------------------------------
            tables_updated = 0
            rows_total = 0
            failed_loads = 0
            if raw:
                tables_updated, rows_total, failed_loads = self._transform_and_load(
                    db, raw, journal, mode="replace"
                )

            result = self._build_result(
                t0,
                tables_updated,
                rows_total,
                failed_loads,
                journal=journal,
                include_exhausted=True,
                include_abandoned=True,
            )
            self._apply_extraction_outcome(result, extraction)
            result.skipped_extractions = runner.skipped
            runner.log_latency_summary()

        bound_log.info(
            "retry complete: {} tables, {} rows, {:.1f}s, {} remaining failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
        )
        journal.log_summary()
        return result

    async def run_backfill(
        self,
        *,
        seasons: list[str] | None = None,
        endpoints: list[str] | None = None,
        patterns: list[str] | None = None,
        force: bool = False,
        extract_only: bool = False,
        transform_only: bool = False,
        season_types: list[str] | None = None,
        context_measures: list[str] | None = None,
    ) -> PipelineResult:
        """Run targeted backfill under the optional capture lifecycle."""

        return await self._run_capture_managed(
            lambda: self._run_backfill(
                seasons=seasons,
                endpoints=endpoints,
                patterns=patterns,
                force=force,
                extract_only=extract_only,
                transform_only=transform_only,
                season_types=season_types,
                context_measures=context_measures,
            ),
        )

    async def _run_backfill(
        self,
        *,
        seasons: list[str] | None = None,
        endpoints: list[str] | None = None,
        patterns: list[str] | None = None,
        force: bool = False,
        extract_only: bool = False,
        transform_only: bool = False,
        season_types: list[str] | None = None,
        context_measures: list[str] | None = None,
    ) -> PipelineResult:
        """Targeted backfill with optional force re-extraction.

        Parameters
        ----------
        seasons
            Season strings to backfill, e.g. ``["2015-16", "2016-17"]``.
            Defaults to all seasons.
        endpoints
            Endpoint names to backfill, e.g. ``["box_score_traditional"]``.
        patterns
            Param patterns to backfill, e.g. ``["game", "season"]``.
        force
            Reset matching journal entries before extraction.
        extract_only
            Skip transform+load phase.
        transform_only
            Skip extraction, re-run transforms from DuckDB staging.
        season_types
            Defaults to the full supported season-type universe.
        context_measures
            Optional video context-measure filter. Defaults to all supported measures.
        """
        if context_measures is not None:
            context_measures = list(resolve_video_context_measures(context_measures))
        season_types = self._resolved_season_types(season_types)

        bound_log = cast("_BoundLogger", logger.bind(run_mode="backfill"))
        t0 = time.perf_counter()

        db, journal = self._init_db()
        pp = self._progress

        # ── force reset ──
        if force and not transform_only:
            from nbadb.orchestrate.backfill import BackfillPlanner

            planner = BackfillPlanner(db.duckdb, journal)
            planner.force_reset(
                seasons=seasons,
                endpoints=_with_cume_foundations(endpoints),
                patterns=patterns,
            )
            bound_log.info("backfill: force-reset matching journal entries")

        # ── transform-only path ──
        if transform_only:
            if pp is not None:
                pp.start_phase("Transform (from staging)")
            bound_log.info("backfill: transform-only — loading staging from DuckDB")
            self._materialize_staging_batches(db, endpoints=endpoints, patterns=patterns)
            raw = self._load_staging_from_duckdb(db, endpoints=endpoints, patterns=patterns)
            bound_log.info("backfill: loaded {} staging tables", len(raw))
            if pp is not None:
                pp.update_phase_info(f"{len(raw)} staging tables")

            tables_updated, rows_total, failed_loads = self._transform_and_load(
                db, raw, journal, mode="replace"
            )
            if pp is not None:
                pp.complete_phase()

            return self._build_result(t0, tables_updated, rows_total, failed_loads, journal=journal)

        # ── extraction path ──
        self._enable_ordinary_request_closure_capture()
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery(
                thread_pool=runner._thread_pool,
                run_mode="backfill",
            )
            effective_seasons = seasons if seasons is not None else season_range()

            bound_log.info(
                "backfill: {} seasons, endpoints={}, patterns={}, force={}",
                len(effective_seasons),
                endpoints,
                patterns,
                force,
            )

            if patterns:
                requested_patterns = set(patterns)
            elif endpoints is not None:
                endpoint_set = set(endpoints)
                requested_patterns = {
                    entry.param_pattern
                    for entry in STAGING_MAP
                    if entry.endpoint_name in endpoint_set
                }
                if "league_game_log" in endpoint_set:
                    requested_patterns.add("game")
            else:
                requested_patterns = None
            if endpoints and set(endpoints) & DISCOVERY_SEED_OWNED_ENDPOINTS:
                requested_patterns = set(requested_patterns or ())
                requested_patterns.add("game")
            needs_games = requested_patterns is None or bool({"game", "date"} & requested_patterns)
            needs_players = requested_patterns is None or bool(
                {"player", "player_season"} & requested_patterns
            )
            needs_teams = requested_patterns is None or bool(
                {"team", "team_season"} & requested_patterns
            )
            needs_dates = requested_patterns is None or "date" in requested_patterns
            needs_player_team_season = (
                requested_patterns is None or "player_team_season" in requested_patterns
            )
            if endpoints:
                _require_requested_endpoint_routes(
                    set(endpoints),
                    requested_patterns=set(patterns) if patterns else None,
                    discovery_backed_endpoints=(
                        DISCOVERY_SEED_OWNED_ENDPOINTS if needs_games else frozenset()
                    ),
                )

            # -- 1. Entity discovery (scoped to requested seasons) -----
            if pp is not None:
                pp.start_phase("Discovery")
                pp.update_phase_info(f"scanning {len(effective_seasons)} seasons...")

            game_ids, player_ids, team_ids, game_dates, game_log_df = await self._discover_entities(
                discovery,
                effective_seasons,
                bound_log,
                season_types=season_types,
                include_historical_players=True,
                include_games=needs_games,
                include_players=needs_players,
                include_teams=needs_teams,
                include_dates=needs_dates,
                require_complete=needs_games or needs_players or needs_teams,
            )
            current_team_ids = (
                await self._discover_current_team_ids(discovery, seasons=effective_seasons)
                if needs_teams
                else []
            )
            if needs_player_team_season:
                player_team_result = await self._discover_player_team_season_result(
                    discovery,
                    seasons=effective_seasons,
                    season_types=season_types,
                    run_mode="backfill",
                )
                self._require_complete_player_team_discovery(player_team_result)
                player_team_season_params = self._persist_player_team_season_workloads(
                    player_team_result.params,
                    seasons=effective_seasons,
                    season_types=season_types,
                    covered_pairs=set(player_team_result.covered_pairs),
                )
            else:
                player_team_season_params = []
            if pp is not None:
                pp.complete_phase()

            # -- 2. Build plan and filter by user scope ─────────────────
            plan = build_extraction_plan(
                seasons=effective_seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                season_types=season_types,
                context_measures=context_measures,
            )

            plan = _filter_backfill_plan(
                plan,
                endpoints=endpoints,
                patterns=patterns,
            )
            closure_support_date = date.today()
            request_closure = self._build_ordinary_request_closure(
                runner,
                plan,
                run_mode="backfill",
                support_date=closure_support_date,
                discovery_seed_requested=needs_games,
                recurring_live_requested=False,
            )

            # -- 3. Extract ──────────────────────────────────────────────
            raw: dict[str, pl.DataFrame] = {}
            if not game_log_df.is_empty():
                raw["stg_league_game_log"] = game_log_df

            total_tasks = sum(item.task_count for item in plan)
            if pp is not None:
                pp.start_phase("Extraction", total=total_tasks)

            extraction = await self._extract_all_patterns(
                runner,
                plan=plan,
                seasons=effective_seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                current_team_ids=current_team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                game_log_df=game_log_df,
                include_static=True,
                season_types=season_types,
                context_measures=context_measures,
                run_mode="backfill",
                journal=journal,
                progress_store=self._extraction_progress(),
                persist_results=lambda frames, **metadata: self._persist_staging_to_duckdb(
                    db,
                    frames,
                    replace_existing_chunks=force,
                    **metadata,
                ),
                retain_in_memory=False,
                request_closure_build=request_closure,
            )
            raw.update(extraction.raw)

            # -- 4. Transform + Load ─────────────────────────────────────
            tables_updated = 0
            rows_total = 0
            failed_loads = 0

            if extract_only:
                bound_log.info("extract-only: staged extraction slices persisted incrementally")
            else:
                self._materialize_staging_batches(db, endpoints=endpoints, patterns=patterns)
                raw = self._load_staging_from_duckdb(db, endpoints=endpoints, patterns=patterns)
                if raw and pp is not None:
                    pp.start_phase("Transform & Load")
                    pp.update_phase_info(f"{len(raw)} staging tables")
                if raw:
                    tables_updated, rows_total, failed_loads = self._transform_and_load(
                        db, raw, journal, mode="replace"
                    )
                if raw and pp is not None:
                    pp.complete_phase()

            # -- 5. Result ───────────────────────────────────────────────
            journal.abandon_exhausted()
            result = self._build_result(
                t0, tables_updated, rows_total, failed_loads, journal=journal
            )
            self._apply_extraction_outcome(result, extraction)
            result.skipped_extractions = runner.skipped
            runner.log_latency_summary()

        bound_log.info(
            "backfill complete: {} tables, {} rows, {:.1f}s, {} extract failures, {} load failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
            result.failed_loads,
        )
        journal.log_summary()
        return result

    def _load_staging_from_duckdb(
        self,
        db: DBManager,
        *,
        endpoints: list[str] | None = None,
        patterns: list[str] | None = None,
        include_empty: bool = False,
    ) -> dict[str, pl.DataFrame]:
        """Read existing staging tables from DuckDB into memory.

        When *endpoints* or *patterns* are provided, only staging keys
        that match the filter are loaded (scoped backfill).  Otherwise
        all staging keys are loaded.
        """
        from nbadb.orchestrate.staging_map import get_all_staging_keys

        if endpoints is not None or patterns is not None:
            ep_set = set(endpoints) if endpoints else None
            pat_set = set(patterns) if patterns else None
            keys = [
                e.staging_key
                for e in STAGING_MAP
                if (ep_set is None or e.endpoint_name in ep_set)
                and (pat_set is None or e.param_pattern in pat_set)
            ]
        else:
            keys = get_all_staging_keys()

        from nbadb.core.types import validate_sql_identifier

        raw: dict[str, pl.DataFrame] = {}
        for key in keys:
            try:
                safe_key = validate_sql_identifier(key)
                df = db.duckdb.execute(f"SELECT * FROM {safe_key}").pl()
                if include_empty or not df.is_empty():
                    raw[key] = df
                    logger.debug("loaded staging {}: {} rows", key, df.shape[0])
            except duckdb.CatalogException:
                pass  # Table doesn't exist yet
        return raw
