"""Tests for nbadb.orchestrate.orchestrator.Orchestrator."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import duckdb
import polars as pl
import pytest

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.errors import ExtractionError, ParserInputCaptureIntegrityError
from nbadb.core.types import (
    ALL_STAR_CANCELLED_UPSTREAM_UNAVAILABLE_REASON,
    ALL_STAR_PRE_HISTORY_UPSTREAM_UNAVAILABLE_REASON,
    VIDEO_CONTEXT_MEASURES,
)
from nbadb.extract.bronze import LogicalCallReceiptBinding, canonical_parameters_sha256
from nbadb.extract.registry import EndpointRegistry
from nbadb.orchestrate.capture_session import (
    CaptureSessionState,
    IncompleteCaptureIdentity,
    PrivateCaptureSession,
    PrivateGenerationIdentity,
)
from nbadb.orchestrate.cume_workload_contract import (
    CumeEntityKind,
    CumeWorkloadContractError,
)
from nbadb.orchestrate.discovery import (
    DiscoveryCaptureCompletion,
    DiscoveryCaptureScopeKey,
    GameDiscoveryResult,
    PlayerIdDiscoveryResult,
    PlayerTeamSeasonDiscoveryResult,
)
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope
from nbadb.orchestrate.extraction_progress import ExtractionProgressStore
from nbadb.orchestrate.extractor_runner import PatternExtractionResult
from nbadb.orchestrate.init_coverage import InitDiscoveryCoverageError
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.live_snapshot import (
    LivePlanAuthorityBindingFactory,
    LiveSnapshotExtraction,
    LiveSnapshotWarehouse,
    LiveSourceCallResult,
    RawRequestCaptureContextFactory,
)
from nbadb.orchestrate.orchestrator import (
    DEFAULT_SEASON_TYPES,
    ExtractionOutcome,
    Orchestrator,
    PipelineResult,
    _apply_player_shard,
    _derive_cume_workloads,
    _entries_for_successor_authority,
    _filter_backfill_plan,
    _require_requested_endpoint_routes,
    _source_logical_provider_parameter_authority,
    _validate_successor_execution_authority,
    validate_successor_runtime_plan,
)
from nbadb.orchestrate.planning import CumeFoundationDependency, ExtractionPlanItem
from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    SourceScopeReplacementAttestation,
    StagingBatchStore,
    frame_content_hash,
)
from nbadb.orchestrate.staging_map import STAGING_MAP, StagingEntry
from nbadb.orchestrate.successor_execution_plan import (
    SealedUpdateExecutionDispatch,
    SuccessorExecutionPlan,
)
from nbadb.orchestrate.successor_planning_contract import finalize_successor_update_intent
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDispatchPhase,
    SealedProviderDispatch,
)
from nbadb.orchestrate.successor_transform_authority import TransformOutputAttestation
from nbadb.orchestrate.successor_update_contract import (
    SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS,
    BaselineAssuranceIdentity,
    CallMutability,
    DeltaDisposition,
    ObservedDeltaReceipt,
    RequestedRouteScope,
    SuccessorGenerationState,
    SuccessorUpdateContractError,
    SuccessorUpdateIntent,
    SuccessorUpdateMode,
    SuccessorUpdateTransaction,
    canonical_sha256,
)
from nbadb.orchestrate.transformers import (
    TransformerDiscoveryError,
    expected_transform_output_tables,
)
from tests.unit.orchestrate._raw_request_test_support import (
    raw_request_assurance_authority,
)
from tests.unit.orchestrate.test_live_snapshot import (
    BoxScore,
    NbaDbLiveHTTP,
    Odds,
    PlayByPlay,
    ScoreBoard,
    _complete_live_payload,
    _ExactLiveAuthorityHarness,
    _live_response,
)
from tests.unit.orchestrate.test_live_snapshot import (
    _settings as _live_settings,
)
from tests.unit.orchestrate.test_raw_request_orchestrator_integration import (
    _manifest_authority,
    _w2_runtime,
)
from tests.unit.orchestrate.test_successor_coordinator import (
    _baseline as _successor_baseline,
)
from tests.unit.orchestrate.test_successor_coordinator import (
    _planning as _successor_planning,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_settings():
    s = MagicMock()
    s.duckdb_path = MagicMock()
    s.duckdb_path.exists.return_value = True
    s.data_dir = Path("data/nbadb")
    s.sqlite_path = MagicMock()
    s.semaphore_tiers = {"default": 5}
    s.endpoint_semaphore_limits = {}
    s.pbp_chunk_size = 50
    s.daily_lookback_days = 7
    s.default_chunk_size = 500
    s.thread_pool_size = 4
    s.rate_limit = 10.0
    s.endpoint_rate_limits = {}
    s.adaptive_rate_min = 1.0
    s.adaptive_rate_recovery = 50
    return s


def _mock_capture_session() -> MagicMock:
    session = MagicMock(spec=PrivateCaptureSession)
    session.closed = False
    session.state = CaptureSessionState.ADMITTED
    return session


def _live_w2_fixture(
    tmp_path: Path,
) -> tuple[
    dict[str, object],
    RawRequestCaptureContextFactory,
    LivePlanAuthorityBindingFactory,
]:
    """Return one coherent Raw V2/W2/live-plan test authority bundle."""

    execution = RawRequestExecutionIdentityV1(
        source_sha="a" * 40,
        run_id=7001,
        run_attempt=1,
        chain_id="live-chain",
        lane_id="live-lane",
    )
    runtime_root = tmp_path / "live-w2"
    runtime_root.mkdir()
    authority = _ExactLiveAuthorityHarness()

    def context_for(endpoint_name: str, params: dict[str, object]):
        context = authority.context_for(endpoint_name, params)
        return context.model_copy(
            update={
                "source_sha": execution.source_sha,
                "run_id": execution.run_id,
                "run_attempt": execution.run_attempt,
                "chain_id": execution.chain_id,
                "lane_id": execution.lane_id,
            }
        )

    kwargs = {
        "raw_request_execution_identity": execution,
        "raw_request_assurance_authority": raw_request_assurance_authority(
            source_sha=execution.source_sha
        ),
        "raw_request_manifest_authority": _manifest_authority(execution=execution),
        "w2_preparation_runtime": _w2_runtime(runtime_root, execution),
        "live_raw_request_capture_context_factory": context_for,
        "live_plan_authority_binding_factory": authority.plan_for,
    }
    return kwargs, context_for, authority.plan_for


def _live_w2_kwargs(tmp_path: Path) -> dict[str, object]:
    return _live_w2_fixture(tmp_path)[0]


def _exact_live_extraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    game_ids: tuple[str, ...],
    raw_context_factory: RawRequestCaptureContextFactory,
    plan_factory: LivePlanAuthorityBindingFactory,
) -> LiveSnapshotExtraction:
    """Build exact source evidence through the production live warehouse."""

    endpoint_classes = [ScoreBoard]
    if game_ids:
        endpoint_classes.append(Odds)
        for _game_id in game_ids:
            endpoint_classes.extend((PlayByPlay, BoxScore))
    responses = iter(
        _live_response(_complete_live_payload(endpoint_cls)) for endpoint_cls in endpoint_classes
    )
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: next(responses),
    )
    warehouse = LiveSnapshotWarehouse(
        settings=_live_settings(tmp_path),
        public_recurring=True,
        raw_request_capture_context_factory=raw_context_factory,
        live_plan_authority_binding_factory=plan_factory,
    )
    return warehouse.extract_source_calls(
        game_ids=list(game_ids),
        snapshot_at=datetime(2026, 8, 13, tzinfo=UTC),
    )


def _successor_transform_scratch_kwargs(tmp_path: Path) -> dict[str, object]:
    scratch = (tmp_path / "successor-transform-scratch").resolve()
    scratch.mkdir()
    observed = scratch.stat()
    return {
        "successor_transform_scratch_parent": scratch,
        "expected_successor_transform_scratch_identity": (observed.st_dev, observed.st_ino),
        "successor_transform_scratch_max_bytes": 1_048_576,
    }


def _expected_transform_count() -> int:
    return len(expected_transform_output_tables(include_live=True))


def _successor_registry_kwargs(
    transaction: SuccessorUpdateTransaction,
    *additional_endpoint_names: str,
) -> dict[str, object]:
    registry = EndpointRegistry()
    endpoint_names = sorted(
        {
            *(scope.endpoint_name for scope in transaction.intent.requested_scopes),
            *additional_endpoint_names,
        }
    )
    for endpoint_name in endpoint_names:
        extractor = type(
            f"Synthetic{endpoint_name.title().replace('_', '')}",
            (),
            {"endpoint_name": endpoint_name},
        )
        registry.register(extractor)  # type: ignore[arg-type]
    return {
        "successor_registry": registry,
        "successor_registry_authority": registry.capture_authority(),
    }


def _mock_live_extraction(
    *,
    game_ids: tuple[str, ...] = (),
    provider_call_count: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        game_ids=game_ids,
        source_calls=tuple(object() for _ in range(provider_call_count)),
    )


def _successor_candidate(
    *,
    route_id: str,
    route_contract_sha256: str,
    parameters: Mapping[str, object],
    provider_authority_sha256: str,
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
) -> SuccessorUpdateTransaction:
    scope = RequestedRouteScope.from_parameters(
        endpoint_name=route_id.split(":", 1)[0],
        route_id=route_id,
        route_contract_sha256=route_contract_sha256,
        parameters=parameters,
        mutability=CallMutability.MUTABLE,
    )
    return _successor_candidate_for_scopes(
        scopes=(scope,),
        provider_authority_sha256=provider_authority_sha256,
        mode=mode,
    )


def _successor_candidate_for_scopes(
    *,
    scopes: tuple[RequestedRouteScope, ...],
    provider_authority_sha256: str,
    mode: SuccessorUpdateMode = SuccessorUpdateMode.DAILY,
) -> SuccessorUpdateTransaction:
    baseline = BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=238,
        chain_id="initial-full",
        source_sha="a" * 40,
        coverage_fingerprint="1" * 64,
        data_tree_fingerprint="2" * 64,
        remote_bundle_fingerprint_sha256="3" * 64,
        installed_public_tree_sha256="c" * 64,
        installed_public_tree_bytes=len(b"synthetic-baseline-public"),
        assured_manifest_sha256="4" * 64,
        terminal_assurance_report_sha256="5" * 64,
        private_baseline_receipt_sha256="6" * 64,
        checkpoint_database_sha256="7" * 64,
        checkpoint_report_sha256="8" * 64,
        contract_blocked_evidence_sha256="9" * 64,
        provider_authority_sha256=provider_authority_sha256,
    )
    plan = _successor_plan_for_scopes(scopes)
    intent = SuccessorUpdateIntent(
        baseline_identity_sha256=baseline.identity_sha256,
        planning_generation_manifest_sha256="0" * 64,
        successor_execution_plan_sha256=plan.identity_sha256,
        planned_route_replacement_bindings_sha256=(plan.planned_route_replacement_bindings_sha256),
        mode=mode,
        source_sha="b" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        requested_scopes=scopes,
    )
    return SuccessorUpdateTransaction.candidate(
        generation=1,
        baseline=baseline,
        intent=intent,
    )


def _successor_plan_for_scopes(
    scopes: tuple[RequestedRouteScope, ...],
) -> SuccessorExecutionPlan:
    """Build one deterministic exact-plan fixture over current route bodies."""

    routes = staging_route_contract_bundle().by_route_id
    grouped: dict[tuple[str, str], list[RequestedRouteScope]] = {}
    for scope in scopes:
        grouped.setdefault((scope.endpoint_name, scope.scope_sha256), []).append(scope)
    dispatches: list[SealedUpdateExecutionDispatch] = []
    for order, ((_endpoint, _parameters_sha256), group) in enumerate(sorted(grouped.items())):
        exact_scopes = tuple(group)
        first = exact_scopes[0]
        patterns = {
            route.param_pattern
            for scope in exact_scopes
            if (route := routes.get(scope.route_id)) is not None
        }
        pattern = next(iter(patterns)) if len(patterns) == 1 else "season"
        dispatches.append(
            SealedUpdateExecutionDispatch(
                order=order,
                sealed_dispatch=SealedProviderDispatch.from_parameters(
                    phase=PlanningDispatchPhase.UPDATE,
                    endpoint_name=first.endpoint_name,
                    requested_scope_identity_sha256s=tuple(
                        scope.identity_sha256 for scope in exact_scopes
                    ),
                    parameters=first.parameters,
                    pattern=pattern,
                    staging_route_ids=tuple(scope.route_id for scope in exact_scopes),
                    dependency_identity_sha256s=(
                        canonical_sha256(
                            {
                                "fixture_dependency_scopes": sorted(
                                    scope.identity_sha256 for scope in exact_scopes
                                )
                            }
                        ),
                    ),
                ),
                requested_scopes=exact_scopes,
            )
        )
    sorted_scopes = tuple(sorted(scopes, key=lambda scope: scope.identity_sha256))
    return SuccessorExecutionPlan(
        baseline_identity_sha256="a" * 64,
        planning_generation_id="fixture-generation",
        planning_request_sha256="b" * 64,
        planning_artifact_identity_sha256="c" * 64,
        planning_manifest_sha256="d" * 64,
        sealed_dispatch_inventory_sha256="e" * 64,
        requested_route_scopes_sha256=canonical_sha256(
            [scope.to_dict() for scope in sorted_scopes]
        ),
        dispatches=tuple(dispatches),
    )


def _successor_replacement_attestations(
    transaction: SuccessorUpdateTransaction,
    dispatch: SealedUpdateExecutionDispatch,
    *,
    logical_root: str,
    persisted_content_sha256: str = "b" * 64,
) -> tuple[SourceScopeReplacementAttestation, ...]:
    routes = staging_route_contract_bundle().by_route_id
    return tuple(
        SourceScopeReplacementAttestation(
            successor_generation_sha256=transaction.generation_identity_sha256,
            source_scope_sha256=dispatch.parameters_sha256,
            staging_key=routes[scope.route_id].staging_key,
            canonical_frame_format=CANONICAL_FRAME_FORMAT,
            frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
            frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
            prior_persisted_content_sha256="a" * 64,
            persisted_content_sha256=persisted_content_sha256,
            persisted_schema_sha256="c" * 64,
            persisted_row_count=7,
            logical_call_receipt_sha256=logical_root,
            provider_authority_sha256=routes[scope.route_id].provider_authority_sha256,
            logical_parameters_sha256=dispatch.parameters_sha256,
            result_route_id=scope.route_id,
        )
        for scope in dispatch.requested_scopes
    )


@contextmanager
def _execute_successor_plan_harness(
    orch: Orchestrator,
    *,
    transaction: SuccessorUpdateTransaction,
    plan: SuccessorExecutionPlan,
    journal: MagicMock,
    runner: MagicMock,
):
    db = MagicMock()
    orch._db = db
    orch._journal = journal
    resolved = tuple(
        _entries_for_successor_authority(transaction, dispatch) for dispatch in plan.dispatches
    )
    expected_transform_count = _expected_transform_count()
    orch._transform_output_attestations = tuple(
        MagicMock() for _ in range(expected_transform_count)
    )
    with (
        patch(
            "nbadb.orchestrate.orchestrator.validate_successor_runtime_plan",
            return_value=resolved,
        ),
        patch.object(orch, "_init_db", return_value=(db, journal)),
        patch.object(orch, "_build_runner", return_value=runner),
        patch.object(orch, "_materialize_staging_batches"),
        patch.object(orch, "_export_successor_staging_resources"),
        patch.object(orch, "_load_staging_from_duckdb", return_value={}),
        patch.object(
            orch,
            "_transform_and_load",
            return_value=(expected_transform_count, 0, 0),
        ),
        patch.object(
            orch,
            "_build_result",
            return_value=PipelineResult(tables_updated=expected_transform_count),
        ),
    ):
        yield db


def _live_scopes(
    calls: tuple[tuple[str, Mapping[str, object]], ...],
) -> tuple[RequestedRouteScope, ...]:
    bundle = staging_route_contract_bundle()
    scopes: list[RequestedRouteScope] = []
    for endpoint_name, params in calls:
        routes = tuple(route for route in bundle.routes if route.endpoint_name == endpoint_name)
        assert routes
        scopes.extend(
            RequestedRouteScope.from_parameters(
                endpoint_name=route.endpoint_name,
                route_id=route.route_id,
                route_contract_sha256=route.contract_sha256,
                parameters=params,
                mutability=CallMutability.MUTABLE,
            )
            for route in routes
        )
    return tuple(scopes)


def _live_source_call(
    *,
    endpoint_name: str,
    params: Mapping[str, object],
    row_count: int,
    receipt_seed: str,
) -> LiveSourceCallResult:
    routes = tuple(
        route
        for route in staging_route_contract_bundle().routes
        if route.endpoint_name == endpoint_name
    )
    assert routes
    params_json = json.dumps(
        dict(params),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    frames = tuple(
        (
            route.staging_key,
            pl.DataFrame({"value": list(range(row_count))})
            if row_count
            else pl.DataFrame(schema={"value": pl.Int64}),
        )
        for route in routes
    )
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=receipt_seed * 64,
        endpoint_name=endpoint_name,
        logical_parameters_sha256=canonical_parameters_sha256(params),
        provider_authority_sha256=routes[0].provider_authority_sha256,
        result_route_ids=tuple(sorted(route.route_id for route in routes)),
    )
    return LiveSourceCallResult(
        endpoint_name=endpoint_name,
        parameters_json=params_json,
        _frame_items=frames,
        expected_staging_keys=tuple(route.staging_key for route in routes),
        result_route_ids_by_staging_key=tuple(
            (route.staging_key, route.route_id) for route in routes
        ),
        receipt_binding=binding,
    )


# Common patch targets
_DB_MANAGER = "nbadb.orchestrate.orchestrator.DBManager"
_JOURNAL = "nbadb.orchestrate.orchestrator.PipelineJournal"
_REGISTRY = "nbadb.orchestrate.orchestrator._global_registry"
_DISCOVERY = "nbadb.orchestrate.orchestrator.EntityDiscovery"
_RUNNER = "nbadb.orchestrate.orchestrator.ExtractorRunner"
_ALL_SEASON_TYPES = DEFAULT_SEASON_TYPES
_TRANSFORMERS = "nbadb.orchestrate.orchestrator.discover_all_transformers"
_VALIDATE_TRANSFORMERS = "nbadb.orchestrate.orchestrator.require_complete_transformer_universe"
_PIPELINE = "nbadb.orchestrate.orchestrator.TransformPipeline"
_LOADER = "nbadb.orchestrate.orchestrator.create_multi_loader"
_GET_BY_PATTERN = "nbadb.orchestrate.planning.get_by_pattern"
_SEASON_RANGE = "nbadb.orchestrate.orchestrator.season_range"
_CURRENT_SEASON = "nbadb.orchestrate.orchestrator.current_season"
_RECENT_SEASONS = "nbadb.orchestrate.orchestrator.recent_seasons"


def _mock_runner(**overrides):
    """Create a MagicMock runner that supports ``async with``."""
    runner = MagicMock()
    runner.run_pattern = AsyncMock(return_value={})

    async def _default_pattern_result(
        _pattern,
        params,
        entries,
        *,
        persist_chunk_results=None,
        **_kwargs,
    ):
        foundation_endpoints = {
            "cume_stats_player_games",
            "cume_stats_team_games",
        }
        if entries and {entry.endpoint_name for entry in entries} <= foundation_endpoints:
            if persist_chunk_results is not None:
                source_results = []
                for param_set in params:
                    for entry in entries:
                        frame = pl.DataFrame(schema={"matchup": pl.String, "game_id": pl.String})
                        route = next(
                            route
                            for route in staging_route_contract_bundle().routes
                            if route.endpoint_name == entry.endpoint_name
                            and route.staging_key == entry.staging_key
                        )
                        receipt_binding = LogicalCallReceiptBinding(
                            logical_call_receipt_sha256=canonical_sha256(
                                {
                                    "endpoint_name": entry.endpoint_name,
                                    "parameters": param_set,
                                    "route_id": route.route_id,
                                }
                            ),
                            endpoint_name=entry.endpoint_name,
                            logical_parameters_sha256=canonical_parameters_sha256(param_set),
                            provider_authority_sha256=route.provider_authority_sha256,
                            result_route_ids=(route.route_id,),
                        )
                        source_results.append(
                            {
                                "frames": {entry.staging_key: frame},
                                "source_endpoint_name": entry.endpoint_name,
                                "source_params_json": json.dumps(param_set, sort_keys=True),
                                "expected_staging_keys": (entry.staging_key,),
                                "receipt_binding": receipt_binding,
                                "result_route_ids_by_staging_key": (
                                    (entry.staging_key, route.route_id),
                                ),
                            }
                        )
                persist_chunk_results(
                    {},
                    chunk_index=0,
                    chunk_params=params,
                    expected_staging_keys=[entry.staging_key for entry in entries],
                    source_results=source_results,
                )
            calls = len(params) * len(entries)
            return PatternExtractionResult(
                frames={},
                eligible_calls=calls,
                success_count=calls,
                scheduled_calls=calls,
            )
        return PatternExtractionResult(frames={})

    runner.run_pattern_result = AsyncMock(side_effect=_default_pattern_result)
    runner._capture_contract_factory = None
    runner.skipped = 0
    runner.skipped_due_to_journal = 0
    runner.planned_calls = 0
    runner.failed_current_run = 0
    runner.__aenter__ = AsyncMock(return_value=runner)
    runner.__aexit__ = AsyncMock(return_value=False)
    for k, v in overrides.items():
        setattr(runner, k, v)
    return runner


def _build_orchestrator_with_mocks():
    """Set up Orchestrator with all external deps mocked."""
    settings = _mock_settings()

    orch = Orchestrator(settings=settings)

    # Mock DB + Journal
    db = MagicMock()
    db.duckdb = MagicMock()
    journal = MagicMock()
    journal.get_failed.return_value = []
    journal.set_watermark = MagicMock()
    journal.has_done_entries.return_value = False
    journal.clear_journal = MagicMock()

    orch._db = db
    orch._journal = journal

    return orch, db, journal


def _cume_player_plan_item() -> ExtractionPlanItem:
    foundation = StagingEntry(
        "cume_stats_player_games",
        "stg_cume_player_games",
        "player_season",
        season_type_capability="supported",
        supported_season_types=("Regular Season",),
    )
    dependent = StagingEntry(
        "cume_stats_player",
        "stg_cume_player",
        "player_season",
        use_multi=True,
        season_type_capability="supported",
        supported_season_types=("Regular Season",),
    )
    return ExtractionPlanItem(
        label="player x season (cume_stats_player) [Regular Season]",
        pattern="player_season",
        entries=[foundation],
        params=[
            {
                "player_id": 201939,
                "season": "2024-25",
                "season_type": "Regular Season",
            }
        ],
        priority=3,
        cume_dependency=CumeFoundationDependency(
            dependent_entries=(dependent,),
            entity_kind=CumeEntityKind.PLAYER,
        ),
    )


def _game_discovery_result(
    *,
    game_ids: list[str] | None = None,
    game_log_df: pl.DataFrame | None = None,
    seasons: tuple[str, ...] = ("2024-25",),
    season_types: tuple[str, ...] = ("Regular Season",),
    covered_combos: frozenset[tuple[str, str]] | None = None,
) -> GameDiscoveryResult:
    frame = (
        game_log_df
        if game_log_df is not None
        else pl.DataFrame(
            {
                "game_id": pl.Series("game_id", [], dtype=pl.String),
                "game_date": pl.Series("game_date", [], dtype=pl.String),
            }
        )
    )
    requested_combos = frozenset(
        (season, season_type) for season in seasons for season_type in season_types
    )
    effective_covered = requested_combos if covered_combos is None else covered_combos
    return GameDiscoveryResult(
        game_ids=game_ids or [],
        raw=frame,
        requested_combos=requested_combos,
        covered_combos=effective_covered,
        frames_by_combo={combo: frame for combo in effective_covered},
    )


def _player_id_discovery_result(
    season: str,
    *,
    ids: list[int] | None = None,
) -> PlayerIdDiscoveryResult:
    return PlayerIdDiscoveryResult(
        ids=[201566] if ids is None else ids,
        requested_season=season,
        source="common_all_players",
    )


def _player_team_discovery_result(
    *,
    params: list[dict[str, int | str]] | None = None,
    seasons: tuple[str, ...] = ("2024-25",),
    season_types: tuple[str, ...] = ("Regular Season",),
    covered_pairs: frozenset[tuple[str, str]] | None = None,
    upstream_unavailable_pairs: dict[tuple[str, str], str] | None = None,
) -> PlayerTeamSeasonDiscoveryResult:
    requested_pairs = frozenset(
        (season, season_type) for season in seasons for season_type in season_types
    )
    effective_covered = requested_pairs if covered_pairs is None else covered_pairs
    return PlayerTeamSeasonDiscoveryResult(
        params=params or [],
        requested_pairs=requested_pairs,
        covered_pairs=effective_covered,
        upstream_unavailable_pairs=upstream_unavailable_pairs or {},
    )


# ---------------------------------------------------------------------------
# PipelineResult tests
# ---------------------------------------------------------------------------


class TestPipelineResult:
    def test_defaults(self):
        r = PipelineResult()
        assert r.tables_updated == 0
        assert r.rows_total == 0
        assert r.errors == []

    def test_fields_settable(self):
        r = PipelineResult(tables_updated=5, rows_total=1000, failed_extractions=2)
        assert r.tables_updated == 5
        assert r.rows_total == 1000
        assert r.failed_extractions == 2


# ---------------------------------------------------------------------------
# Orchestrator init tests
# ---------------------------------------------------------------------------


class TestOrchestratorInit:
    def test_creates_successfully(self):
        settings = _mock_settings()
        orch = Orchestrator(settings=settings)
        assert orch._settings is settings

    def test_capture_session_must_already_be_admitted_and_open(self):
        session = _mock_capture_session()
        session.state = CaptureSessionState.CREATED

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="must already be admitted and open",
        ):
            Orchestrator(settings=_mock_settings(), capture_session=session)

    def test_build_runner_receives_only_the_injected_capture_factory(self):
        session = _mock_capture_session()
        runner = MagicMock()
        journal = MagicMock()
        orch = Orchestrator(settings=_mock_settings(), capture_session=session)

        with patch(_REGISTRY), patch(_RUNNER, return_value=runner) as runner_cls:
            assert orch._build_runner(journal) is runner

        assert runner_cls.call_args.kwargs["capture_contract_factory"] is session.contract_for
        assert runner_cls.call_args.kwargs["call_admission"] is None

    def test_no_capture_keeps_runner_factory_disabled(self):
        runner = MagicMock()
        journal = MagicMock()
        orch = Orchestrator(settings=_mock_settings())

        with patch(_REGISTRY), patch(_RUNNER, return_value=runner) as runner_cls:
            assert orch._build_runner(journal) is runner

        assert runner_cls.call_args.kwargs["capture_contract_factory"] is None
        assert runner_cls.call_args.kwargs["call_admission"] is None

    def test_successor_requires_capture_and_exact_candidate_state(self):
        route = staging_route_contract_bundle().routes[0]
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters={"candidate": "scope"},
            provider_authority_sha256=route.provider_authority_sha256,
        )

        with pytest.raises(
            SuccessorUpdateContractError,
            match="requires an admitted private capture session",
        ):
            Orchestrator(settings=_mock_settings(), successor_transaction=candidate)

        candidate_scope = candidate.intent.requested_scopes[0]
        candidate_plan = _successor_plan_for_scopes(candidate.intent.requested_scopes)
        candidate_binding = candidate_plan.planned_route_replacement_bindings[0]
        invalid_state = candidate.mark_built(
            observed_delta_receipts=(
                ObservedDeltaReceipt(
                    baseline_identity_sha256=candidate.baseline.identity_sha256,
                    update_intent_sha256=candidate.intent.identity_sha256,
                    source_sha=candidate.intent.source_sha,
                    requested_scope_sha256=candidate_scope.identity_sha256,
                    execution_dispatch_identity_sha256=(
                        candidate_binding.execution_dispatch_identity_sha256
                    ),
                    planning_dependency_identity_sha256s=(
                        candidate_binding.planning_dependency_identity_sha256s
                    ),
                    disposition=DeltaDisposition.OBSERVED,
                    logical_call_receipt_sha256="e" * 64,
                    prior_persisted_content_sha256="f" * 64,
                    source_scope_replacement_sha256="1" * 64,
                    persisted_content_sha256="2" * 64,
                    persisted_schema_sha256="3" * 64,
                    persisted_row_count=1,
                ),
            ),
        )
        assert invalid_state.state is SuccessorGenerationState.BUILT
        with pytest.raises(SuccessorUpdateContractError, match="exact candidate"):
            Orchestrator(
                settings=_mock_settings(),
                capture_session=_mock_capture_session(),
                successor_transaction=invalid_state,
            )


class TestSuccessorExactPlanRuntimeSeam:
    def test_honest_evidence_intent_and_plan_authority_reconcile(
        self,
        tmp_path,
    ) -> None:
        public_root = tmp_path / "public"
        public_root.mkdir()
        (public_root / "nba.duckdb").write_bytes(b"baseline")
        baseline = _successor_baseline(public_root)
        evidence = _successor_planning(baseline)
        intent = finalize_successor_update_intent(evidence)
        transaction = SuccessorUpdateTransaction.candidate(
            generation=1,
            baseline=baseline,
            intent=intent,
        )

        assert evidence.execution_plan.planning_manifest_sha256 != (
            intent.planning_generation_manifest_sha256
        )
        _validate_successor_execution_authority(transaction, evidence.execution_plan)

    def test_execution_plan_identity_drift_is_rejected(self, tmp_path) -> None:
        public_root = tmp_path / "public"
        public_root.mkdir()
        (public_root / "nba.duckdb").write_bytes(b"baseline")
        baseline = _successor_baseline(public_root)
        evidence = _successor_planning(baseline)
        intent = finalize_successor_update_intent(evidence)
        transaction = SuccessorUpdateTransaction.candidate(
            generation=1,
            baseline=baseline,
            intent=intent,
        )
        drifted_plan = replace(evidence.execution_plan, planning_request_sha256="f" * 64)

        with pytest.raises(
            SuccessorUpdateContractError,
            match="successor_execution_plan_sha256",
        ):
            _validate_successor_execution_authority(transaction, drifted_plan)

    def test_runtime_preflight_independently_rejects_duplicate_logical_calls(
        self,
        tmp_path,
    ) -> None:
        public_root = tmp_path / "public"
        public_root.mkdir()
        (public_root / "nba.duckdb").write_bytes(b"baseline")
        baseline = _successor_baseline(public_root)
        evidence = _successor_planning(baseline)
        intent = finalize_successor_update_intent(evidence)
        transaction = SuccessorUpdateTransaction.candidate(
            generation=1,
            baseline=baseline,
            intent=intent,
        )
        plan = evidence.execution_plan
        first = plan.dispatches[0]
        duplicate_scope = RequestedRouteScope.from_parameters(
            endpoint_name=first.endpoint_name,
            route_id="fixture_endpoint:stg_duplicate:9",
            route_contract_sha256="f" * 64,
            parameters=first.parameters,
            mutability=CallMutability.MUTABLE,
        )
        duplicate_dispatches = (
            replace(first, order=0),
            SealedUpdateExecutionDispatch(
                order=1,
                sealed_dispatch=SealedProviderDispatch.from_parameters(
                    phase=PlanningDispatchPhase.UPDATE,
                    endpoint_name=first.endpoint_name,
                    requested_scope_identity_sha256s=(duplicate_scope.identity_sha256,),
                    parameters=first.parameters,
                    pattern=first.pattern,
                    staging_route_ids=(duplicate_scope.route_id,),
                    dependency_identity_sha256s=first.dependency_identity_sha256s,
                ),
                requested_scopes=(duplicate_scope,),
            ),
        )
        object.__setattr__(plan, "dispatches", duplicate_dispatches)

        with (
            patch("nbadb.orchestrate.orchestrator._entries_for_successor_authority") as entries,
            pytest.raises(SuccessorUpdateContractError, match="logical provider call"),
        ):
            validate_successor_runtime_plan(transaction, plan)

        entries.assert_not_called()

    def test_staging_map_result_routes_are_unique_and_match_contract(self) -> None:
        route_ids = tuple(
            f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
            for entry in STAGING_MAP
        )

        assert len(route_ids) == len(staging_route_contract_bundle().routes)
        assert len(set(route_ids)) == len(route_ids)

    def test_sealed_multi_route_order_maps_positionally(self) -> None:
        bundle = staging_route_contract_bundle()
        route_ids = (
            "schedule:stg_schedule_weeks:1",
            "schedule:stg_schedule:0",
        )
        parameters = {"season": "2025-26"}
        scopes = tuple(
            RequestedRouteScope.from_parameters(
                endpoint_name="schedule",
                route_id=route_id,
                route_contract_sha256=bundle.by_route_id[route_id].contract_sha256,
                parameters=parameters,
                mutability=CallMutability.MUTABLE,
            )
            for route_id in route_ids
        )
        transaction = _successor_candidate_for_scopes(
            scopes=scopes,
            provider_authority_sha256=bundle.by_route_id[route_ids[0]].provider_authority_sha256,
        )
        sealed = SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name="schedule",
            requested_scope_identity_sha256s=tuple(scope.identity_sha256 for scope in scopes),
            parameters=parameters,
            pattern="season",
            staging_route_ids=route_ids,
            dependency_identity_sha256s=("a" * 64,),
        )
        dispatch = SealedUpdateExecutionDispatch(
            order=0,
            sealed_dispatch=sealed,
            requested_scopes=scopes,
        )

        entries = _entries_for_successor_authority(transaction, dispatch)

        assert tuple(entry.staging_key for entry in entries) == (
            "stg_schedule_weeks",
            "stg_schedule",
        )

    def test_checkpoint_closes_database_but_not_admitted_capture(self) -> None:
        capture = _mock_capture_session()
        orch = Orchestrator(settings=_mock_settings(), capture_session=capture)
        db = MagicMock()
        orch._db = db
        orch._journal = MagicMock()

        orch._checkpoint_and_close_successor_database()

        db.duckdb.execute.assert_called_once_with("CHECKPOINT")
        db.close.assert_called_once_with()
        assert orch._db is None
        assert orch._journal is None
        capture.close.assert_not_called()

    def test_staging_reload_can_retain_present_empty_table(self) -> None:
        orch = Orchestrator(settings=_mock_settings())
        db = MagicMock()
        relation = MagicMock()
        relation.pl.return_value = pl.DataFrame(schema={"game_id": pl.String})
        db.duckdb.execute.return_value = relation

        with patch(
            "nbadb.orchestrate.staging_map.get_all_staging_keys",
            return_value=["stg_empty"],
        ):
            default = orch._load_staging_from_duckdb(db)
            including_empty = orch._load_staging_from_duckdb(db, include_empty=True)

        assert default == {}
        assert tuple(including_empty) == ("stg_empty",)
        assert including_empty["stg_empty"].is_empty()

    @pytest.mark.asyncio
    async def test_exact_execution_uses_intent_time_and_one_strict_materialization(
        self,
        tmp_path,
    ) -> None:
        public_root = tmp_path / "public"
        public_root.mkdir()
        (public_root / "nba.duckdb").write_bytes(b"baseline")
        baseline = _successor_baseline(public_root)
        evidence = _successor_planning(baseline)
        intent = finalize_successor_update_intent(evidence)
        transaction = SuccessorUpdateTransaction.candidate(
            generation=1,
            baseline=baseline,
            intent=intent,
        )
        capture = _mock_capture_session()
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=capture,
            successor_transaction=transaction,
        )
        db = MagicMock()
        journal = MagicMock()
        journal.load_successor_replacement_attestations.return_value = ()
        orch._db = db
        orch._journal = journal
        runner = MagicMock()
        runner.run_pattern_result = AsyncMock(
            return_value=PatternExtractionResult(
                frames={},
                eligible_calls=1,
                success_count=1,
                scheduled_calls=1,
            )
        )
        runner.skipped = 0
        resolved = tuple(
            (StagingEntry("ep", f"stg_ep_{index}", "season"),)
            for index, _dispatch in enumerate(evidence.execution_plan.dispatches)
        )
        expected_transform_count = _expected_transform_count()
        orch._transform_output_attestations = tuple(
            MagicMock() for _ in range(expected_transform_count)
        )

        with (
            patch(
                "nbadb.orchestrate.orchestrator.validate_successor_runtime_plan",
                return_value=resolved,
            ) as validate,
            patch.object(orch, "_init_db", return_value=(db, journal)),
            patch.object(orch, "_build_runner", return_value=runner),
            patch.object(orch, "_require_complete_successor_receipts"),
            patch.object(orch, "_materialize_staging_batches") as materialize,
            patch.object(orch, "_export_successor_staging_resources") as export_staging,
            patch.object(orch, "_load_staging_from_duckdb", return_value={}) as reload_staging,
            patch.object(
                orch,
                "_transform_and_load",
                return_value=(expected_transform_count, 0, 0),
            ) as transform,
            patch.object(
                orch,
                "_build_result",
                return_value=PipelineResult(tables_updated=expected_transform_count),
            ),
        ):
            result = await orch.execute_successor_plan(evidence.execution_plan)

        exact_snapshot = datetime(2026, 8, 13, tzinfo=UTC)
        validate.assert_called_once_with(transaction, evidence.execution_plan)
        assert runner.run_pattern_result.await_count == len(evidence.execution_plan.dispatches)
        for call in runner.run_pattern_result.await_args_list:
            assert call.kwargs["snapshot_at"] == exact_snapshot
            assert call.kwargs["support_date"] == exact_snapshot.date()
            assert call.kwargs["required_route_ids"]
        materialize.assert_called_once_with(db)
        export_staging.assert_called_once_with(
            db,
            staging_keys=tuple(
                sorted(entry.staging_key for entries in resolved for entry in entries)
            ),
        )
        reload_staging.assert_called_once_with(db, include_empty=True)
        assert transform.call_args.kwargs == {
            "mode": "replace",
            "require_complete_transforms": True,
            "materialize_empty_outputs": True,
            "include_live_transforms": True,
            "successor_watermark_season": "2025-26",
        }
        assert db.duckdb.execute.call_count == 2
        assert "information_schema.tables" in db.duckdb.execute.call_args_list[0].args[0]
        assert db.duckdb.execute.call_args_list[1].args == ("CHECKPOINT",)
        db.close.assert_called_once_with()
        assert result.result.tables_updated == expected_transform_count

    @pytest.mark.asyncio
    async def test_execute_successor_plan_skips_committed_members_and_continues_outstanding(
        self,
    ) -> None:
        route = staging_route_contract_bundle().by_route_id["league_game_log:stg_league_game_log:0"]
        scopes = tuple(
            RequestedRouteScope.from_parameters(
                endpoint_name=route.endpoint_name,
                route_id=route.route_id,
                route_contract_sha256=route.contract_sha256,
                parameters={"season": season, "season_type": "Regular Season"},
                mutability=CallMutability.MUTABLE,
            )
            for season in ("2022-23", "2023-24", "2024-25")
        )
        transaction = _successor_candidate_for_scopes(
            scopes=scopes,
            provider_authority_sha256=route.provider_authority_sha256,
        )
        plan = _successor_plan_for_scopes(scopes)
        assert len(plan.dispatches) == 3
        committed = plan.dispatches[:-1]
        outstanding = plan.dispatches[-1]
        committed_roots = tuple(f"{index + 1:064x}" for index in range(len(committed)))
        attestations = tuple(
            attestation
            for dispatch, logical_root in zip(committed, committed_roots, strict=True)
            for attestation in _successor_replacement_attestations(
                transaction,
                dispatch,
                logical_root=logical_root,
            )
        )
        session = _mock_capture_session()
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=transaction,
        )
        journal = MagicMock(spec=PipelineJournal)
        journal.load_successor_replacement_attestations.return_value = attestations
        committed_parameter_digests = {dispatch.parameters_sha256 for dispatch in committed}

        async def run_pattern_result(
            _pattern: str,
            param_sets: list[dict[str, object]],
            _entries: object,
            **_kwargs: object,
        ) -> PatternExtractionResult:
            digest = canonical_parameters_sha256(param_sets[0])
            if digest in committed_parameter_digests:
                raise AssertionError("completed successor dispatch reached the provider")
            active = next(
                dispatch for dispatch in plan.dispatches if dispatch.parameters_sha256 == digest
            )
            orch._record_successor_replacements(
                _successor_replacement_attestations(
                    transaction,
                    active,
                    logical_root="a" * 64,
                    persisted_content_sha256="e" * 64,
                )
            )
            return PatternExtractionResult(
                frames={},
                eligible_calls=1,
                success_count=1,
                scheduled_calls=1,
            )

        runner = MagicMock()
        runner.skipped = 0
        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        with _execute_successor_plan_harness(
            orch,
            transaction=transaction,
            plan=plan,
            journal=journal,
            runner=runner,
        ):
            result = await orch.execute_successor_plan(plan)

        assert runner.run_pattern_result.await_count == 1
        executed = runner.run_pattern_result.await_args
        assert executed.args[1] == [outstanding.parameters]
        assert executed.kwargs["required_route_ids"] == outstanding.staging_route_ids
        assert {receipt.requested_scope_sha256 for receipt in orch.successor_delta_receipts} == {
            scope.identity_sha256 for scope in scopes
        }
        for dispatch, logical_root in zip(committed, committed_roots, strict=True):
            dispatch_receipts = tuple(
                receipt
                for receipt in orch.successor_delta_receipts
                if receipt.execution_dispatch_identity_sha256 == dispatch.identity_sha256
            )
            assert dispatch_receipts
            assert {receipt.logical_call_receipt_sha256 for receipt in dispatch_receipts} == {
                logical_root
            }
        restored = session.restore_completed_bindings.call_args.args[0]
        assert tuple(binding.logical_call_receipt_sha256 for binding in restored) == (
            tuple(sorted(committed_roots))
        )
        assert result.result.tables_updated == _expected_transform_count()

    @pytest.mark.asyncio
    async def test_execute_successor_plan_skips_committed_live_root_and_continues_outstanding(
        self,
    ) -> None:
        bundle = staging_route_contract_bundle()
        scopes = _live_scopes(
            (
                ("live_score_board", {}),
                ("live_box_score", {"game_id": "0022500001"}),
            )
        )
        assert scopes
        assert {scope.endpoint_name for scope in scopes} <= SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS
        transaction = _successor_candidate_for_scopes(
            scopes=scopes,
            provider_authority_sha256=bundle.by_route_id[
                scopes[0].route_id
            ].provider_authority_sha256,
        )
        plan = _successor_plan_for_scopes(scopes)
        by_endpoint = {dispatch.endpoint_name: dispatch for dispatch in plan.dispatches}
        assert set(by_endpoint) == {"live_score_board", "live_box_score"}
        committed = by_endpoint["live_box_score"]
        outstanding = by_endpoint["live_score_board"]
        assert len(committed.staging_route_ids) == 7
        assert len(outstanding.staging_route_ids) == 1
        committed_root = "c" * 64
        attestations = _successor_replacement_attestations(
            transaction,
            committed,
            logical_root=committed_root,
        )
        session = _mock_capture_session()
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=transaction,
        )
        journal = MagicMock(spec=PipelineJournal)
        journal.load_successor_replacement_attestations.return_value = attestations

        async def run_pattern_result(
            _pattern: str,
            param_sets: list[dict[str, object]],
            _entries: object,
            **_kwargs: object,
        ) -> PatternExtractionResult:
            digest = canonical_parameters_sha256(param_sets[0])
            if digest == committed.parameters_sha256:
                raise AssertionError("completed live replacement root reached the provider")
            if digest != outstanding.parameters_sha256:
                raise AssertionError("unexpected successor dispatch reached the provider")
            orch._record_successor_replacements(
                _successor_replacement_attestations(
                    transaction,
                    outstanding,
                    logical_root="d" * 64,
                    persisted_content_sha256="e" * 64,
                )
            )
            return PatternExtractionResult(
                frames={},
                eligible_calls=1,
                success_count=1,
                scheduled_calls=1,
            )

        runner = MagicMock()
        runner.skipped = 0
        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        with (
            _execute_successor_plan_harness(
                orch,
                transaction=transaction,
                plan=plan,
                journal=journal,
                runner=runner,
            ),
            patch.object(
                orch,
                "_extract_successor_live_snapshot",
                side_effect=AssertionError(
                    "completed live replacement root re-entered live snapshot"
                ),
            ),
            patch.object(
                orch,
                "_persist_successor_live_snapshot",
                side_effect=AssertionError(
                    "completed live replacement root re-entered live persist"
                ),
            ),
        ):
            result = await orch.execute_successor_plan(plan)

        assert runner.run_pattern_result.await_count == 1
        executed = runner.run_pattern_result.await_args
        assert executed.args[0] == outstanding.pattern == "live"
        assert executed.args[1] == [outstanding.parameters]
        assert executed.kwargs["required_route_ids"] == outstanding.staging_route_ids
        assert {receipt.requested_scope_sha256 for receipt in orch.successor_delta_receipts} == {
            scope.identity_sha256 for scope in scopes
        }
        committed_receipts = tuple(
            receipt
            for receipt in orch.successor_delta_receipts
            if receipt.execution_dispatch_identity_sha256 == committed.identity_sha256
        )
        assert len(committed_receipts) == 7
        assert {receipt.logical_call_receipt_sha256 for receipt in committed_receipts} == {
            committed_root
        }
        restored = session.restore_completed_bindings.call_args.args[0]
        assert restored == (
            LogicalCallReceiptBinding(
                logical_call_receipt_sha256=committed_root,
                endpoint_name="live_box_score",
                logical_parameters_sha256=committed.parameters_sha256,
                provider_authority_sha256=bundle.by_route_id[
                    committed.staging_route_ids[0]
                ].provider_authority_sha256,
                result_route_ids=tuple(sorted(committed.staging_route_ids)),
            ),
        )
        assert result.result.tables_updated == _expected_transform_count()

    @pytest.mark.asyncio
    async def test_execute_successor_plan_skips_committed_live_odds_and_continues_play_by_play(
        self,
    ) -> None:
        bundle = staging_route_contract_bundle()
        scopes = _live_scopes(
            (
                ("live_odds", {}),
                ("live_play_by_play", {"game_id": "0022500001"}),
            )
        )
        assert scopes
        assert {scope.endpoint_name for scope in scopes} <= SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS
        assert {"live_odds", "live_play_by_play"} <= SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS
        transaction = _successor_candidate_for_scopes(
            scopes=scopes,
            provider_authority_sha256=bundle.by_route_id[
                scopes[0].route_id
            ].provider_authority_sha256,
        )
        plan = _successor_plan_for_scopes(scopes)
        by_endpoint = {dispatch.endpoint_name: dispatch for dispatch in plan.dispatches}
        assert set(by_endpoint) == {"live_odds", "live_play_by_play"}
        committed = by_endpoint["live_odds"]
        outstanding = by_endpoint["live_play_by_play"]
        assert len(committed.staging_route_ids) == 1
        assert len(outstanding.staging_route_ids) == 1
        committed_root = "c" * 64
        attestations = _successor_replacement_attestations(
            transaction,
            committed,
            logical_root=committed_root,
        )
        session = _mock_capture_session()
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=transaction,
        )
        journal = MagicMock(spec=PipelineJournal)
        journal.load_successor_replacement_attestations.return_value = attestations

        async def run_pattern_result(
            _pattern: str,
            param_sets: list[dict[str, object]],
            _entries: object,
            **_kwargs: object,
        ) -> PatternExtractionResult:
            digest = canonical_parameters_sha256(param_sets[0])
            if digest == committed.parameters_sha256:
                raise AssertionError("completed live_odds digest reached the provider")
            if digest != outstanding.parameters_sha256:
                raise AssertionError("unexpected successor dispatch reached the provider")
            orch._record_successor_replacements(
                _successor_replacement_attestations(
                    transaction,
                    outstanding,
                    logical_root="d" * 64,
                    persisted_content_sha256="e" * 64,
                )
            )
            return PatternExtractionResult(
                frames={},
                eligible_calls=1,
                success_count=1,
                scheduled_calls=1,
            )

        runner = MagicMock()
        runner.skipped = 0
        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        with (
            _execute_successor_plan_harness(
                orch,
                transaction=transaction,
                plan=plan,
                journal=journal,
                runner=runner,
            ),
            patch.object(
                orch,
                "_extract_successor_live_snapshot",
                side_effect=AssertionError(
                    "completed live_odds replacement root re-entered live snapshot"
                ),
            ),
            patch.object(
                orch,
                "_persist_successor_live_snapshot",
                side_effect=AssertionError(
                    "completed live_odds replacement root re-entered live persist"
                ),
            ),
        ):
            result = await orch.execute_successor_plan(plan)

        assert runner.run_pattern_result.await_count == 1
        executed = runner.run_pattern_result.await_args
        assert executed.args[0] == outstanding.pattern == "live"
        assert executed.args[1] == [outstanding.parameters]
        assert executed.kwargs["required_route_ids"] == outstanding.staging_route_ids
        assert {receipt.requested_scope_sha256 for receipt in orch.successor_delta_receipts} == {
            scope.identity_sha256 for scope in scopes
        }
        committed_receipts = tuple(
            receipt
            for receipt in orch.successor_delta_receipts
            if receipt.execution_dispatch_identity_sha256 == committed.identity_sha256
        )
        assert len(committed_receipts) == 1
        assert {receipt.logical_call_receipt_sha256 for receipt in committed_receipts} == {
            committed_root
        }
        restored = session.restore_completed_bindings.call_args.args[0]
        assert restored == (
            LogicalCallReceiptBinding(
                logical_call_receipt_sha256=committed_root,
                endpoint_name="live_odds",
                logical_parameters_sha256=committed.parameters_sha256,
                provider_authority_sha256=bundle.by_route_id[
                    committed.staging_route_ids[0]
                ].provider_authority_sha256,
                result_route_ids=tuple(sorted(committed.staging_route_ids)),
            ),
        )
        assert result.result.tables_updated == _expected_transform_count()

    @pytest.mark.asyncio
    async def test_multi_route_logical_receipt_crash_resume_keeps_one_root(self) -> None:
        route_ids = (
            "schedule:stg_schedule_weeks:1",
            "schedule:stg_schedule:0",
        )
        routes = staging_route_contract_bundle().by_route_id
        scopes = tuple(
            RequestedRouteScope.from_parameters(
                endpoint_name="schedule",
                route_id=route_id,
                route_contract_sha256=routes[route_id].contract_sha256,
                parameters={"season": season},
                mutability=CallMutability.MUTABLE,
            )
            for season in ("2024-25", "2025-26")
            for route_id in route_ids
        )
        transaction = _successor_candidate_for_scopes(
            scopes=scopes,
            provider_authority_sha256=routes[route_ids[0]].provider_authority_sha256,
        )
        plan = _successor_plan_for_scopes(scopes)
        assert len(plan.dispatches) == 2
        assert all(len(dispatch.staging_route_ids) == 2 for dispatch in plan.dispatches)
        committed = plan.dispatches[0]
        outstanding = plan.dispatches[1]
        committed_root = "d" * 64
        complete_attestations = _successor_replacement_attestations(
            transaction,
            committed,
            logical_root=committed_root,
        )
        session = _mock_capture_session()
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=transaction,
        )
        journal = MagicMock(spec=PipelineJournal)
        runner = MagicMock()
        runner.skipped = 0

        async def run_pattern_result(
            _pattern: str,
            param_sets: list[dict[str, object]],
            _entries: object,
            **_kwargs: object,
        ) -> PatternExtractionResult:
            digest = canonical_parameters_sha256(param_sets[0])
            if digest == committed.parameters_sha256:
                raise AssertionError("completed multi-route dispatch reached the provider")
            if digest != outstanding.parameters_sha256:
                raise AssertionError("unexpected successor dispatch reached the provider")
            orch._record_successor_replacements(
                _successor_replacement_attestations(
                    transaction,
                    outstanding,
                    logical_root="e" * 64,
                    persisted_content_sha256="f" * 64,
                )
            )
            return PatternExtractionResult(
                frames={},
                eligible_calls=1,
                success_count=1,
                scheduled_calls=1,
            )

        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        journal.load_successor_replacement_attestations.return_value = complete_attestations[:1]
        with (
            _execute_successor_plan_harness(
                orch,
                transaction=transaction,
                plan=plan,
                journal=journal,
                runner=runner,
            ),
            pytest.raises(SuccessorUpdateContractError, match="exactly cover"),
        ):
            await orch.execute_successor_plan(plan)

        runner.run_pattern_result.assert_not_called()
        assert orch.successor_delta_receipts == ()
        session.restore_completed_bindings.assert_not_called()

        journal.load_successor_replacement_attestations.return_value = complete_attestations
        with _execute_successor_plan_harness(
            orch,
            transaction=transaction,
            plan=plan,
            journal=journal,
            runner=runner,
        ):
            result = await orch.execute_successor_plan(plan)

        assert runner.run_pattern_result.await_count == 1
        executed = runner.run_pattern_result.await_args
        assert executed.args[1] == [outstanding.parameters]
        assert executed.kwargs["required_route_ids"] == outstanding.staging_route_ids
        committed_receipts = tuple(
            receipt
            for receipt in orch.successor_delta_receipts
            if receipt.execution_dispatch_identity_sha256 == committed.identity_sha256
        )
        assert len(committed_receipts) == 2
        assert {receipt.logical_call_receipt_sha256 for receipt in committed_receipts} == {
            committed_root
        }
        restored = session.restore_completed_bindings.call_args.args[0]
        assert len(restored) == 1
        assert restored == (
            LogicalCallReceiptBinding(
                logical_call_receipt_sha256=committed_root,
                endpoint_name="schedule",
                logical_parameters_sha256=committed.parameters_sha256,
                provider_authority_sha256=routes[route_ids[0]].provider_authority_sha256,
                result_route_ids=tuple(sorted(committed.staging_route_ids)),
            ),
        )
        assert result.result.tables_updated == _expected_transform_count()

    @pytest.mark.asyncio
    async def test_execute_successor_plan_skips_every_live_and_update_root_and_keeps_multi_route(
        self,
    ) -> None:
        bundle = staging_route_contract_bundle()
        live_scopes = _live_scopes(
            (
                ("live_score_board", {}),
                ("live_odds", {}),
                ("live_play_by_play", {"game_id": "0022500001"}),
                ("live_box_score", {"game_id": "0022500001"}),
            )
        )
        assert {scope.endpoint_name for scope in live_scopes} == (
            SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS
        )
        update_route = bundle.by_route_id["league_game_log:stg_league_game_log:0"]
        update_scopes = (
            RequestedRouteScope.from_parameters(
                endpoint_name=update_route.endpoint_name,
                route_id=update_route.route_id,
                route_contract_sha256=update_route.contract_sha256,
                parameters={"season": "2025-26", "season_type": "Regular Season"},
                mutability=CallMutability.MUTABLE,
            ),
        )
        schedule_route_ids = (
            "schedule:stg_schedule_weeks:1",
            "schedule:stg_schedule:0",
        )
        schedule_scopes = tuple(
            RequestedRouteScope.from_parameters(
                endpoint_name="schedule",
                route_id=route_id,
                route_contract_sha256=bundle.by_route_id[route_id].contract_sha256,
                parameters={"season": "2025-26"},
                mutability=CallMutability.MUTABLE,
            )
            for route_id in schedule_route_ids
        )
        scopes = (*live_scopes, *update_scopes, *schedule_scopes)
        transaction = _successor_candidate_for_scopes(
            scopes=scopes,
            provider_authority_sha256=bundle.by_route_id[
                live_scopes[0].route_id
            ].provider_authority_sha256,
        )
        plan = _successor_plan_for_scopes(scopes)
        by_endpoint = {dispatch.endpoint_name: dispatch for dispatch in plan.dispatches}
        assert set(by_endpoint) == {
            *SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS,
            "league_game_log",
            "schedule",
        }
        outstanding = by_endpoint["league_game_log"]
        committed = tuple(dispatch for dispatch in plan.dispatches if dispatch is not outstanding)
        attestations = tuple(
            attestation
            for index, dispatch in enumerate(committed)
            for attestation in _successor_replacement_attestations(
                transaction,
                dispatch,
                logical_root=f"{index + 1:064x}",
            )
        )
        session = _mock_capture_session()
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=transaction,
        )
        journal = MagicMock(spec=PipelineJournal)
        journal.load_successor_replacement_attestations.return_value = attestations
        committed_digests = {dispatch.parameters_sha256 for dispatch in committed}

        async def run_pattern_result(
            _pattern: str,
            param_sets: list[dict[str, object]],
            _entries: object,
            **_kwargs: object,
        ) -> PatternExtractionResult:
            digest = canonical_parameters_sha256(param_sets[0])
            if digest in committed_digests:
                raise AssertionError("completed replacement root reached the provider")
            if digest != outstanding.parameters_sha256:
                raise AssertionError("unexpected successor dispatch reached the provider")
            orch._record_successor_replacements(
                _successor_replacement_attestations(
                    transaction,
                    outstanding,
                    logical_root="e" * 64,
                    persisted_content_sha256="f" * 64,
                )
            )
            return PatternExtractionResult(
                frames={},
                eligible_calls=1,
                success_count=1,
                scheduled_calls=1,
            )

        runner = MagicMock()
        runner.skipped = 0
        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        with (
            _execute_successor_plan_harness(
                orch,
                transaction=transaction,
                plan=plan,
                journal=journal,
                runner=runner,
            ),
            patch.object(
                orch,
                "_extract_successor_live_snapshot",
                side_effect=AssertionError(
                    "completed live replacement root re-entered live snapshot"
                ),
            ),
            patch.object(
                orch,
                "_persist_successor_live_snapshot",
                side_effect=AssertionError(
                    "completed live replacement root re-entered live persist"
                ),
            ),
        ):
            result = await orch.execute_successor_plan(plan)

        assert runner.run_pattern_result.await_count == 1
        executed = runner.run_pattern_result.await_args
        assert executed.args[1] == [outstanding.parameters]
        assert executed.kwargs["required_route_ids"] == outstanding.staging_route_ids
        assert {receipt.requested_scope_sha256 for receipt in orch.successor_delta_receipts} == {
            scope.identity_sha256 for scope in scopes
        }
        for index, dispatch in enumerate(committed):
            dispatch_receipts = tuple(
                receipt
                for receipt in orch.successor_delta_receipts
                if receipt.execution_dispatch_identity_sha256 == dispatch.identity_sha256
            )
            assert dispatch_receipts
            assert {receipt.logical_call_receipt_sha256 for receipt in dispatch_receipts} == {
                f"{index + 1:064x}"
            }
            assert len(dispatch_receipts) == len(dispatch.staging_route_ids)
        restored = session.restore_completed_bindings.call_args.args[0]
        assert {binding.endpoint_name for binding in restored} == {
            dispatch.endpoint_name for dispatch in committed
        }
        schedule_binding = next(
            binding for binding in restored if binding.endpoint_name == "schedule"
        )
        assert schedule_binding.result_route_ids == tuple(
            sorted(by_endpoint["schedule"].staging_route_ids)
        )
        live_box_binding = next(
            binding for binding in restored if binding.endpoint_name == "live_box_score"
        )
        assert len(live_box_binding.result_route_ids) == 7
        assert result.result.tables_updated == _expected_transform_count()

    def test_exact_staging_refresh_replaces_all_secondary_publication_formats(
        self,
        tmp_path,
    ) -> None:
        settings = _mock_settings()
        settings.data_dir = tmp_path
        settings.sqlite_path = tmp_path / "nba.sqlite"
        settings.formats = ["sqlite", "duckdb", "csv", "parquet"]
        transaction = _successor_candidate_for_scopes(
            scopes=(
                RequestedRouteScope.from_parameters(
                    endpoint_name="league_game_log",
                    route_id="league_game_log:stg_league_game_log:0",
                    route_contract_sha256="1" * 64,
                    parameters={"season": "2025-26", "season_type": "Regular Season"},
                    mutability=CallMutability.MUTABLE,
                ),
            ),
            provider_authority_sha256="2" * 64,
        )
        orch = Orchestrator(
            settings=settings,
            capture_session=_mock_capture_session(),
            successor_transaction=transaction,
        )
        db = MagicMock()
        frame = pl.DataFrame(schema={"game_id": pl.String})
        db.duckdb.execute.return_value.pl.return_value = frame
        sqlite_loader = MagicMock()
        csv_loader = MagicMock()
        parquet_loader = MagicMock()

        with (
            patch(
                "nbadb.load.sqlite.SQLiteLoader",
                return_value=sqlite_loader,
            ) as sqlite_type,
            patch("nbadb.load.csv_loader.CSVLoader", return_value=csv_loader) as csv_type,
            patch(
                "nbadb.load.parquet_loader.ParquetLoader",
                return_value=parquet_loader,
            ) as parquet_type,
        ):
            orch._export_successor_staging_resources(
                db,
                staging_keys=("stg_league_game_log", "stg_league_game_log"),
            )

        db.duckdb.execute.assert_called_once_with("SELECT * FROM stg_league_game_log")
        sqlite_type.assert_called_once_with(settings.sqlite_path)
        csv_type.assert_called_once_with(tmp_path / "csv")
        parquet_type.assert_called_once_with(tmp_path / "parquet")
        for loader in (sqlite_loader, csv_loader, parquet_loader):
            loader.load.assert_called_once_with(
                "stg_league_game_log",
                frame,
                mode="replace",
            )

    def test_exact_staging_refresh_writes_matching_real_resources(self, tmp_path) -> None:
        import sqlite3

        settings = _mock_settings()
        settings.data_dir = tmp_path
        settings.sqlite_path = tmp_path / "nba.sqlite"
        settings.formats = ["sqlite", "duckdb", "csv", "parquet"]
        transaction = _successor_candidate_for_scopes(
            scopes=(
                RequestedRouteScope.from_parameters(
                    endpoint_name="league_game_log",
                    route_id="league_game_log:stg_league_game_log:0",
                    route_contract_sha256="1" * 64,
                    parameters={"season": "2025-26", "season_type": "Regular Season"},
                    mutability=CallMutability.MUTABLE,
                ),
            ),
            provider_authority_sha256="2" * 64,
        )
        orch = Orchestrator(
            settings=settings,
            capture_session=_mock_capture_session(),
            successor_transaction=transaction,
        )
        connection = duckdb.connect()
        try:
            connection.execute(
                "CREATE TABLE stg_league_game_log AS "
                "SELECT '0022500001'::VARCHAR AS game_id, 2025::BIGINT AS season_year"
            )
            orch._export_successor_staging_resources(
                SimpleNamespace(duckdb=connection),  # type: ignore[arg-type]
                staging_keys=("stg_league_game_log",),
            )
        finally:
            connection.close()

        expected = {"game_id": ["0022500001"], "season_year": [2025]}
        assert (
            pl.read_csv(
                tmp_path / "csv" / "stg_league_game_log.csv",
                schema_overrides={"game_id": pl.String},
            ).to_dict(as_series=False)
            == expected
        )
        assert (
            pl.read_parquet(
                tmp_path / "parquet" / "stg_league_game_log" / "stg_league_game_log.parquet"
            ).to_dict(as_series=False)
            == expected
        )
        with sqlite3.connect(settings.sqlite_path) as sqlite_connection:
            assert sqlite_connection.execute(
                "SELECT game_id, season_year FROM stg_league_game_log"
            ).fetchall() == [("0022500001", 2025)]

    @pytest.mark.asyncio
    async def test_exact_staging_refresh_failure_blocks_transform_and_checkpoints(
        self,
        tmp_path,
    ) -> None:
        public_root = tmp_path / "public"
        public_root.mkdir()
        (public_root / "nba.duckdb").write_bytes(b"baseline")
        baseline = _successor_baseline(public_root)
        evidence = _successor_planning(baseline)
        transaction = SuccessorUpdateTransaction.candidate(
            generation=1,
            baseline=baseline,
            intent=finalize_successor_update_intent(evidence),
        )
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=_mock_capture_session(),
            successor_transaction=transaction,
        )
        db = MagicMock()
        journal = MagicMock()
        journal.load_successor_replacement_attestations.return_value = ()
        orch._db = db
        orch._journal = journal
        runner = MagicMock()
        runner.skipped = 0
        runner.run_pattern_result = AsyncMock(
            return_value=PatternExtractionResult(
                frames={},
                eligible_calls=1,
                success_count=1,
                scheduled_calls=1,
            )
        )
        resolved = tuple(
            (StagingEntry("ep", f"stg_ep_{index}", "season"),)
            for index, _dispatch in enumerate(evidence.execution_plan.dispatches)
        )

        with (
            patch(
                "nbadb.orchestrate.orchestrator.validate_successor_runtime_plan",
                return_value=resolved,
            ),
            patch.object(orch, "_init_db", return_value=(db, journal)),
            patch.object(orch, "_build_runner", return_value=runner),
            patch.object(orch, "_require_complete_successor_receipts"),
            patch.object(orch, "_materialize_staging_batches"),
            patch.object(
                orch,
                "_export_successor_staging_resources",
                side_effect=OSError("staging publication failed"),
            ),
            patch.object(orch, "_transform_and_load") as transform,
            pytest.raises(OSError, match="staging publication failed"),
        ):
            await orch.execute_successor_plan(evidence.execution_plan)

        transform.assert_not_called()
        assert db.duckdb.execute.call_count == 2
        assert "information_schema.tables" in db.duckdb.execute.call_args_list[0].args[0]
        assert db.duckdb.execute.call_args_list[1].args == ("CHECKPOINT",)
        db.close.assert_called_once_with()


class TestOrchestratorCaptureLifecycle:
    def test_successor_live_extraction_uses_admission_and_orchestrator_capture(
        self, tmp_path: Path
    ):
        session = _mock_capture_session()
        settings = _mock_settings()
        route = staging_route_contract_bundle().by_route_id[
            "live_score_board:stg_live_score_board:0"
        ]
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters={},
            provider_authority_sha256=route.provider_authority_sha256,
        )
        orch = Orchestrator(
            settings=settings,
            capture_session=session,
            successor_transaction=candidate,
            **_live_w2_kwargs(tmp_path),
        )
        warehouse = MagicMock()
        extraction = SimpleNamespace(
            game_ids=(),
            source_calls=(),
        )
        warehouse.extract_source_calls.return_value = extraction

        with patch(
            "nbadb.orchestrate.orchestrator.LiveSnapshotWarehouse",
            return_value=warehouse,
        ) as warehouse_cls:
            result = orch._extract_successor_live_snapshot()

        assert result is extraction
        kwargs = warehouse_cls.call_args.kwargs
        assert kwargs["settings"] is settings
        assert kwargs["capture_contract_factory"] is session.contract_for
        assert kwargs["call_admission"].__self__ is orch
        assert kwargs["call_admission"].__func__ is Orchestrator._admit_successor_provider_call
        assert "capture_completion_callback" not in kwargs
        warehouse.extract_source_calls.assert_called_once_with(
            snapshot_at=datetime.fromisoformat(candidate.intent.as_of_utc.replace("Z", "+00:00"))
        )

    def test_out_of_intent_live_call_is_blocked_before_capture_or_provider(self, tmp_path: Path):
        route = staging_route_contract_bundle().by_route_id["live_odds:stg_live_odds:0"]
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters={},
            provider_authority_sha256=route.provider_authority_sha256,
        )
        session = _mock_capture_session()
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=candidate,
            **_successor_registry_kwargs(candidate, *SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS),
            **_live_w2_kwargs(tmp_path),
        )

        with (
            patch("nbadb.extract.base.fetch_live_payloads") as provider,
            pytest.raises(
                SuccessorUpdateContractError,
                match="outside the immutable intent",
            ),
        ):
            orch._extract_successor_live_snapshot()

        session.contract_for.assert_not_called()
        session.record_completed.assert_not_called()
        provider.assert_not_called()

    def test_complete_no_discovery_run_seals_then_closes(self):
        session = _mock_capture_session()
        sealed = MagicMock(spec=PrivateGenerationIdentity)
        session.seal.return_value = sealed
        session.close.return_value = sealed
        orch = Orchestrator(settings=_mock_settings(), capture_session=session)
        expected = PipelineResult(tables_updated=1, rows_total=10)

        with patch.object(orch, "_run_backfill", AsyncMock(return_value=expected)):
            result = asyncio.run(orch.run_backfill(transform_only=True))

        assert result is expected
        session.seal.assert_called_once_with()
        session.close.assert_called_once_with()
        assert orch.capture_identity is sealed

    def test_failed_result_closes_to_incomplete_without_sealing(self):
        session = _mock_capture_session()
        incomplete = MagicMock(spec=IncompleteCaptureIdentity)
        session.close.return_value = incomplete
        orch = Orchestrator(settings=_mock_settings(), capture_session=session)
        failed = PipelineResult(
            failed_extractions=1,
            errors=["durable extraction incomplete"],
        )

        with patch.object(orch, "_run_backfill", AsyncMock(return_value=failed)):
            result = asyncio.run(orch.run_backfill(transform_only=True))

        assert result is failed
        session.seal.assert_not_called()
        session.close.assert_called_once_with()
        assert orch.capture_identity is incomplete

    @pytest.mark.parametrize("failure", [RuntimeError("boom"), asyncio.CancelledError()])
    def test_exception_or_cancellation_closes_to_incomplete(self, failure: BaseException):
        session = _mock_capture_session()
        incomplete = MagicMock(spec=IncompleteCaptureIdentity)
        session.close.return_value = incomplete
        orch = Orchestrator(settings=_mock_settings(), capture_session=session)

        with (
            patch.object(orch, "_run_backfill", AsyncMock(side_effect=failure)),
            pytest.raises(type(failure)),
        ):
            asyncio.run(orch.run_backfill(transform_only=True))

        session.seal.assert_not_called()
        session.close.assert_called_once_with()
        assert orch.capture_identity is incomplete

    def test_capture_required_discovery_receives_factory_and_durable_sink(self):
        session = _mock_capture_session()
        orch = Orchestrator(settings=_mock_settings(), capture_session=session)
        discovery = MagicMock()
        thread_pool = MagicMock()

        with (
            patch(_DISCOVERY, return_value=discovery) as discovery_cls,
        ):
            assert orch._build_discovery(thread_pool=thread_pool, run_mode="daily") is discovery

        kwargs = discovery_cls.call_args.kwargs
        assert kwargs["thread_pool"] is thread_pool
        assert kwargs["settings"] is orch._settings
        assert kwargs["capture_contract_factory"] is session.contract_for
        assert callable(kwargs["capture_completion_sink"])
        assert kwargs["call_admission"] is None

    def test_successor_runner_and_discovery_share_unified_admission(self):
        route = staging_route_contract_bundle().by_route_id["league_game_log:stg_league_game_log:0"]
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters={"season": "2024-25", "season_type": "Regular Season"},
            provider_authority_sha256=route.provider_authority_sha256,
        )
        session = _mock_capture_session()
        registry_kwargs = _successor_registry_kwargs(candidate)
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=candidate,
            **registry_kwargs,
        )

        with (
            patch(_REGISTRY),
            patch(_RUNNER, return_value=MagicMock()) as runner_cls,
            patch(_DISCOVERY, return_value=MagicMock()) as discovery_cls,
        ):
            orch._build_runner(MagicMock())
            orch._build_discovery(run_mode="daily")

        for callback in (
            runner_cls.call_args.kwargs["call_admission"],
            discovery_cls.call_args.kwargs["call_admission"],
        ):
            assert callback.__self__ is orch
            assert callback.__func__ is Orchestrator._admit_successor_provider_call
        assert runner_cls.call_args.kwargs["registry"] is registry_kwargs["successor_registry"]
        assert discovery_cls.call_args.args[0] is registry_kwargs["successor_registry"]

    def test_successor_runner_rejects_registry_class_drift_before_provider(self):
        route = staging_route_contract_bundle().by_route_id["league_game_log:stg_league_game_log:0"]
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters={"season": "2024-25", "season_type": "Regular Season"},
            provider_authority_sha256=route.provider_authority_sha256,
        )
        registry_kwargs = _successor_registry_kwargs(candidate)
        registry = registry_kwargs["successor_registry"]
        assert isinstance(registry, EndpointRegistry)
        replacement = type(
            "ForeignLeagueGameLog",
            (),
            {"endpoint_name": route.endpoint_name},
        )
        registry.register(replacement)  # type: ignore[arg-type]
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=_mock_capture_session(),
            successor_transaction=candidate,
            **registry_kwargs,
        )

        with (
            patch(_RUNNER) as runner_type,
            pytest.raises(SuccessorUpdateContractError, match="registry authority differs"),
        ):
            orch._build_runner(MagicMock())

        runner_type.assert_not_called()

    def test_successor_provider_call_admits_exact_schema_v4_endpoint_scope(self):
        route = staging_route_contract_bundle().by_route_id["league_game_log:stg_league_game_log:0"]
        params = {"season": "2024-25", "season_type": "Regular Season"}
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters=params,
            provider_authority_sha256=route.provider_authority_sha256,
        )
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=_mock_capture_session(),
            successor_transaction=candidate,
            **_successor_registry_kwargs(candidate),
        )

        assert candidate.intent.requested_scopes[0].parameters == params
        assert candidate.intent.requested_scopes[0].scope_sha256 == (
            canonical_parameters_sha256(params)
        )
        orch._admit_successor_provider_call(
            route.endpoint_name,
            dict(params),
            (route.route_id,),
        )

    def test_successor_resume_restores_route_receipt_and_private_root(self):
        route = staging_route_contract_bundle().routes[0]
        params = {"season": "2024-25"}
        transaction = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters=params,
            provider_authority_sha256=route.provider_authority_sha256,
        )
        session = _mock_capture_session()
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=transaction,
        )
        orch._successor_execution_plan = _successor_plan_for_scopes(
            transaction.intent.requested_scopes
        )
        parameters_sha256 = canonical_parameters_sha256(params)
        attestation = SourceScopeReplacementAttestation(
            successor_generation_sha256=transaction.generation_identity_sha256,
            source_scope_sha256=parameters_sha256,
            staging_key=route.staging_key,
            canonical_frame_format=CANONICAL_FRAME_FORMAT,
            frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
            frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
            prior_persisted_content_sha256="a" * 64,
            persisted_content_sha256="b" * 64,
            persisted_schema_sha256="c" * 64,
            persisted_row_count=7,
            logical_call_receipt_sha256="d" * 64,
            provider_authority_sha256=route.provider_authority_sha256,
            logical_parameters_sha256=parameters_sha256,
            result_route_id=route.route_id,
        )
        journal = MagicMock(spec=PipelineJournal)
        journal.load_successor_replacement_attestations.return_value = (attestation,)

        orch._restore_successor_execution_state(journal)

        receipt = orch.successor_delta_receipts[0]
        assert receipt.requested_scope_sha256 == (
            transaction.intent.requested_scopes[0].identity_sha256
        )
        assert receipt.logical_call_receipt_sha256 == "d" * 64
        binding = orch._successor_execution_plan.planned_route_replacement_bindings[0]
        assert receipt.execution_dispatch_identity_sha256 == (
            binding.execution_dispatch_identity_sha256
        )
        assert receipt.planning_dependency_identity_sha256s == (
            binding.planning_dependency_identity_sha256s
        )
        restored = session.restore_completed_bindings.call_args.args[0]
        assert restored == (
            LogicalCallReceiptBinding(
                logical_call_receipt_sha256="d" * 64,
                endpoint_name=route.endpoint_name,
                logical_parameters_sha256=parameters_sha256,
                provider_authority_sha256=route.provider_authority_sha256,
                result_route_ids=(route.route_id,),
            ),
        )

    def test_successor_resume_rejects_incomplete_multi_route_before_capture_restore(self):
        route_ids = (
            "schedule:stg_schedule_weeks:1",
            "schedule:stg_schedule:0",
        )
        routes = staging_route_contract_bundle().by_route_id
        params = {"season": "2025-26"}
        scopes = tuple(
            RequestedRouteScope.from_parameters(
                endpoint_name="schedule",
                route_id=route_id,
                route_contract_sha256=routes[route_id].contract_sha256,
                parameters=params,
                mutability=CallMutability.MUTABLE,
            )
            for route_id in route_ids
        )
        transaction = _successor_candidate_for_scopes(
            scopes=scopes,
            provider_authority_sha256=routes[route_ids[0]].provider_authority_sha256,
        )
        session = _mock_capture_session()
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=transaction,
        )
        orch._successor_execution_plan = _successor_plan_for_scopes(scopes)
        parameters_sha256 = canonical_parameters_sha256(params)
        attestation = SourceScopeReplacementAttestation(
            successor_generation_sha256=transaction.generation_identity_sha256,
            source_scope_sha256=parameters_sha256,
            staging_key=routes[route_ids[0]].staging_key,
            canonical_frame_format=CANONICAL_FRAME_FORMAT,
            frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
            frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
            prior_persisted_content_sha256="a" * 64,
            persisted_content_sha256="b" * 64,
            persisted_schema_sha256="c" * 64,
            persisted_row_count=7,
            logical_call_receipt_sha256="d" * 64,
            provider_authority_sha256=routes[route_ids[0]].provider_authority_sha256,
            logical_parameters_sha256=parameters_sha256,
            result_route_id=route_ids[0],
        )
        journal = MagicMock(spec=PipelineJournal)
        journal.load_successor_replacement_attestations.return_value = (attestation,)

        with pytest.raises(SuccessorUpdateContractError, match="exactly cover"):
            orch._restore_successor_execution_state(journal)

        assert orch.successor_delta_receipts == ()
        session.restore_completed_bindings.assert_not_called()

    @pytest.mark.parametrize(
        ("endpoint_name", "params", "result_route_ids"),
        [
            (
                "league_game_log",
                {"season": "2023-24", "season_type": "Regular Season"},
                ("league_game_log:stg_league_game_log:0",),
            ),
            (
                "player_game_logs",
                {"season": "2024-25", "season_type": "Regular Season"},
                ("league_game_log:stg_league_game_log:0",),
            ),
            (
                "league_game_log",
                {"season": "2024-25", "season_type": "Regular Season"},
                ("player_game_logs:stg_player_game_logs:0",),
            ),
        ],
    )
    def test_successor_provider_call_rejects_out_of_intent_identity(
        self,
        endpoint_name: str,
        params: dict[str, object],
        result_route_ids: tuple[str, ...],
    ):
        route = staging_route_contract_bundle().by_route_id["league_game_log:stg_league_game_log:0"]
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters={"season": "2024-25", "season_type": "Regular Season"},
            provider_authority_sha256=route.provider_authority_sha256,
        )
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=_mock_capture_session(),
            successor_transaction=candidate,
            **_successor_registry_kwargs(candidate, endpoint_name),
        )

        with pytest.raises(SuccessorUpdateContractError, match="outside the immutable intent"):
            orch._admit_successor_provider_call(
                endpoint_name,
                params,
                result_route_ids,
            )

    @pytest.mark.parametrize("mismatch", ["route_contract", "provider_authority"])
    def test_successor_provider_call_rejects_contract_or_provider_mismatch(self, mismatch: str):
        route = staging_route_contract_bundle().by_route_id["league_game_log:stg_league_game_log:0"]
        params = {"season": "2024-25", "season_type": "Regular Season"}
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=(
                "f" * 64 if mismatch == "route_contract" else route.contract_sha256
            ),
            parameters=params,
            provider_authority_sha256=(
                "e" * 64 if mismatch == "provider_authority" else route.provider_authority_sha256
            ),
        )
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=_mock_capture_session(),
            successor_transaction=candidate,
            **_successor_registry_kwargs(candidate),
        )

        with pytest.raises(
            SuccessorUpdateContractError,
            match="differs from route, provider, contract, or parameters",
        ):
            orch._admit_successor_provider_call(
                route.endpoint_name,
                params,
                (route.route_id,),
            )

    def test_discovery_completion_persists_before_recording_private_receipt(self):
        session = _mock_capture_session()
        orch = Orchestrator(settings=_mock_settings(), capture_session=session)
        conn = duckdb.connect(":memory:")
        orch._db = SimpleNamespace(duckdb=conn)  # type: ignore[assignment]
        params = {"season": "2024-25", "season_type": "Regular Season"}
        scope = DiscoveryCaptureScopeKey.from_parameters("league_game_log", params)
        route = "league_game_log:stg_league_game_log:0"
        binding = LogicalCallReceiptBinding(
            logical_call_receipt_sha256="a" * 64,
            endpoint_name="league_game_log",
            logical_parameters_sha256=scope.logical_parameters_sha256,
            provider_authority_sha256="b" * 64,
            result_route_ids=(route,),
        )
        completion = DiscoveryCaptureCompletion(
            scope_key=scope,
            endpoint_name="league_game_log",
            logical_parameters=tuple(sorted(params.items())),
            frame=pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2026-02-28"]}),
            receipt_binding=binding,
        )
        observed_counts: list[int] = []

        def record_completed(_binding: LogicalCallReceiptBinding) -> None:
            count = conn.execute(
                "SELECT count(*) FROM _staging_chunk_journal WHERE logical_call_receipt_sha256 = ?",
                [binding.logical_call_receipt_sha256],
            ).fetchone()[0]
            observed_counts.append(count)

        session.record_completed.side_effect = record_completed
        try:
            orch._persist_discovery_capture_completion(completion, run_mode="daily")
        finally:
            conn.close()

        assert observed_counts == [1]
        session.record_completed.assert_called_once_with(binding)

    def test_close_is_idempotent_and_never_seals(self):
        session = _mock_capture_session()
        incomplete = MagicMock(spec=IncompleteCaptureIdentity)
        session.close.return_value = incomplete
        orch = Orchestrator(settings=_mock_settings(), capture_session=session)
        db = MagicMock()
        orch._db = db
        orch._journal = MagicMock()

        assert orch.close() is incomplete
        assert orch.close() is incomplete

        db.close.assert_called_once_with()
        session.close.assert_called_once_with()
        session.seal.assert_not_called()

    def test_no_capture_run_preserves_legacy_execution(self):
        orch = Orchestrator(settings=_mock_settings())
        expected = PipelineResult(tables_updated=2, rows_total=20)

        with patch.object(orch, "_run_backfill", AsyncMock(return_value=expected)) as operation:
            result = asyncio.run(orch.run_backfill(transform_only=True))

        assert result is expected
        operation.assert_awaited_once()
        assert orch.capture_identity is None


# ---------------------------------------------------------------------------
# _discover_entities tests
# ---------------------------------------------------------------------------


class TestDiscoverEntities:
    def test_skips_unrequested_discovery_calls(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        bound_log = MagicMock()

        mock_discovery = AsyncMock()
        mock_discovery.discover_team_ids.return_value = [1610612737]

        game_ids, player_ids, team_ids, game_dates, game_log_df = asyncio.run(
            orch._discover_entities(
                mock_discovery,
                ["2024-25"],
                bound_log,
                include_historical_players=True,
                include_games=False,
                include_players=False,
                include_teams=True,
                include_dates=False,
            )
        )

        assert game_ids == []
        assert player_ids == []
        assert team_ids == [1610612737]
        assert game_dates == []
        assert game_log_df.is_empty()
        mock_discovery.discover_game_ids_result.assert_not_called()
        mock_discovery.discover_all_player_ids.assert_not_called()
        mock_discovery.discover_game_dates.assert_not_called()
        mock_discovery.discover_team_ids.assert_awaited_once()

    def test_uses_cached_scoped_discovery_artifacts(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        mock_discovery = AsyncMock()

        artifact_store = orch._discovery_artifacts()
        artifact_store.upsert_frame(
            DiscoveryArtifactScope(
                kind="league_game_log",
                seasons=("2024-25",),
                season_types=("Regular Season",),
            ),
            pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]}),
            provenance="test",
        )

        game_ids, player_ids, team_ids, game_dates, game_log_df = asyncio.run(
            orch._discover_entities(
                mock_discovery,
                ["2024-25"],
                bound_log,
                include_games=True,
                include_players=False,
                include_teams=False,
                include_dates=True,
            )
        )

        assert game_ids == ["001"]
        assert player_ids == []
        assert team_ids == []
        assert game_dates == ["2024-10-22"]
        assert game_log_df.shape == (1, 2)
        mock_discovery.discover_game_ids_result.assert_not_called()

    def test_refresh_mutable_entities_bypasses_current_season_game_and_player_caches(
        self, tmp_path
    ):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        artifact_store = orch._discovery_artifacts()
        artifact_store.upsert_frame(
            DiscoveryArtifactScope(
                kind="league_game_log",
                seasons=("2024-25",),
                season_types=("Regular Season",),
            ),
            pl.DataFrame({"game_id": ["old"], "game_date": ["2024-10-22"]}),
            provenance="stale-test-cache",
        )
        artifact_store.upsert_ids(
            DiscoveryArtifactScope(
                kind="player_ids_active",
                seasons=("2024-25",),
                variant="active",
            ),
            [1],
            provenance="stale-test-cache",
        )
        live_frame = pl.DataFrame({"game_id": ["new"], "game_date": ["2025-01-02"]})
        discovery = AsyncMock()
        discovery.discover_game_ids_result.return_value = GameDiscoveryResult(
            game_ids=["new"],
            raw=live_frame,
            requested_combos=frozenset({("2024-25", "Regular Season")}),
            covered_combos=frozenset({("2024-25", "Regular Season")}),
            frames_by_combo={("2024-25", "Regular Season"): live_frame},
        )
        discovery.discover_player_ids.return_value = [1, 2]
        discovery.discover_game_dates.return_value = ["2025-01-02"]

        with patch(_CURRENT_SEASON, return_value="2024-25"):
            game_ids, player_ids, _team_ids, game_dates, game_log_df = asyncio.run(
                orch._discover_entities(
                    discovery,
                    ["2024-25"],
                    bound_log,
                    season_types=["Regular Season"],
                    include_teams=False,
                    refresh_mutable_entities=True,
                )
            )

        assert game_ids == ["new"]
        assert player_ids == [1, 2]
        assert game_dates == ["2025-01-02"]
        assert game_log_df.to_dicts() == live_frame.to_dicts()
        discovery.discover_game_ids_result.assert_awaited_once()
        discovery.discover_player_ids.assert_awaited_once()
        discovery.discover_game_dates.assert_awaited_once()

    def test_historical_single_season_player_discovery_is_season_scoped(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        mock_discovery = AsyncMock()
        mock_discovery.discover_all_player_ids.return_value = [10, 20]

        _game_ids, player_ids, _team_ids, _game_dates, _game_log_df = asyncio.run(
            orch._discover_entities(
                mock_discovery,
                ["1946-47"],
                bound_log,
                include_historical_players=True,
                include_games=False,
                include_players=True,
                include_teams=False,
                include_dates=False,
                season_types=["Regular Season"],
            )
        )

        assert player_ids == [10, 20]
        mock_discovery.discover_all_player_ids.assert_awaited_once_with(season="1946-47")
        cached = orch._discovery_artifacts().load_ids(
            DiscoveryArtifactScope(
                kind="player_ids_all",
                seasons=("1946-47",),
                season_types=(),
                variant="historical",
            )
        )
        assert cached == [10, 20]

    def test_historical_player_cache_is_independent_of_season_type(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        mock_discovery = AsyncMock()
        orch._discovery_artifacts().upsert_ids(
            DiscoveryArtifactScope(
                kind="player_ids_all",
                seasons=("1946-47",),
                season_types=(),
                variant="historical",
            ),
            [10, 20],
            provenance="test",
        )

        _game_ids, player_ids, _team_ids, _game_dates, _game_log_df = asyncio.run(
            orch._discover_entities(
                mock_discovery,
                ["1946-47"],
                bound_log,
                include_historical_players=True,
                include_games=False,
                include_players=True,
                include_teams=False,
                include_dates=False,
                season_types=["All Star"],
            )
        )

        assert player_ids == [10, 20]
        mock_discovery.discover_all_player_ids.assert_not_called()

    def test_require_complete_raises_on_player_discovery_exception(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        mock_discovery = AsyncMock()
        mock_discovery.discover_all_player_ids.side_effect = RuntimeError("upstream timeout")

        with pytest.raises(InitDiscoveryCoverageError, match="discover_player_ids failed"):
            asyncio.run(
                orch._discover_entities(
                    mock_discovery,
                    ["1946-47"],
                    bound_log,
                    include_historical_players=True,
                    include_games=False,
                    include_players=True,
                    include_teams=False,
                    include_dates=False,
                    require_complete=True,
                )
            )

    def test_require_complete_raises_on_empty_historical_player_discovery(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        mock_discovery = AsyncMock()
        mock_discovery.discover_all_player_ids.return_value = []

        with pytest.raises(InitDiscoveryCoverageError, match="player discovery returned no ids"):
            asyncio.run(
                orch._discover_entities(
                    mock_discovery,
                    ["1946-47"],
                    bound_log,
                    include_historical_players=True,
                    include_games=False,
                    include_players=True,
                    include_teams=False,
                    include_dates=False,
                    require_complete=True,
                )
            )

    def test_does_not_cache_partial_game_discovery_as_full_scope(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()

        class _Discovery:
            async def discover_game_ids_result(self, *_args, **_kwargs):
                return GameDiscoveryResult(
                    game_ids=["001"],
                    raw=pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]}),
                    requested_combos=frozenset(
                        {
                            ("2024-25", "Regular Season"),
                            ("2024-25", "Playoffs"),
                        }
                    ),
                    covered_combos=frozenset({("2024-25", "Regular Season")}),
                )

            async def discover_game_dates(self, game_log_df):
                return game_log_df.get_column("game_date").to_list()

        mock_discovery = _Discovery()

        game_ids, _player_ids, _team_ids, game_dates, game_log_df = asyncio.run(
            orch._discover_entities(
                mock_discovery,
                ["2024-25"],
                bound_log,
                include_games=True,
                include_players=False,
                include_teams=False,
                include_dates=True,
                season_types=["Regular Season", "Playoffs"],
            )
        )

        cached = orch._discovery_artifacts().load_frame(
            DiscoveryArtifactScope(
                kind="league_game_log",
                seasons=("2024-25",),
                season_types=("Regular Season", "Playoffs"),
            )
        )
        assert game_ids == []
        assert game_dates == []
        assert game_log_df.is_empty()
        assert cached is None

    def test_reuses_partial_game_discovery_artifacts_for_covered_narrower_scope(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()

        class _Discovery:
            async def discover_game_ids_result(self, *_args, **_kwargs):
                return GameDiscoveryResult(
                    game_ids=["001"],
                    raw=pl.DataFrame({"game_id": ["001"], "game_date": ["2024-10-22"]}),
                    requested_combos=frozenset(
                        {
                            ("2024-25", "Regular Season"),
                            ("2024-25", "Playoffs"),
                        }
                    ),
                    covered_combos=frozenset({("2024-25", "Regular Season")}),
                    frames_by_combo={
                        ("2024-25", "Regular Season"): pl.DataFrame(
                            {"game_id": ["001"], "game_date": ["2024-10-22"]}
                        )
                    },
                )

            async def discover_game_dates(self, game_log_df):
                return game_log_df.get_column("game_date").to_list()

        asyncio.run(
            orch._discover_entities(
                _Discovery(),
                ["2024-25"],
                bound_log,
                include_games=True,
                include_players=False,
                include_teams=False,
                include_dates=True,
                season_types=["Regular Season", "Playoffs"],
            )
        )

        cached_scope = DiscoveryArtifactScope(
            kind="league_game_log",
            seasons=("2024-25",),
            season_types=("Regular Season",),
        )
        cached = orch._discovery_artifacts().load_game_log_frame(cached_scope)

        assert cached is not None
        assert cached.to_dicts() == [{"game_id": "001", "game_date": "2024-10-22"}]

    def test_persists_only_requested_and_explicitly_covered_game_combo_frames(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        regular_combo = ("2024-25", "Regular Season")
        playoff_combo = ("2024-25", "Playoffs")
        unrequested_combo = ("2024-25", "Pre Season")
        regular_frame = pl.DataFrame({"game_id": ["regular"], "game_date": ["2024-10-22"]})
        playoff_frame = pl.DataFrame({"game_id": ["playoff"], "game_date": ["2025-04-19"]})
        unrequested_frame = pl.DataFrame({"game_id": ["preseason"], "game_date": ["2024-10-04"]})
        discovery = AsyncMock()
        discovery.discover_game_ids_result.return_value = GameDiscoveryResult(
            game_ids=["regular", "playoff", "preseason"],
            raw=pl.concat([regular_frame, playoff_frame, unrequested_frame]),
            requested_combos=frozenset({regular_combo, playoff_combo}),
            covered_combos=frozenset({regular_combo, unrequested_combo}),
            frames_by_combo={
                regular_combo: regular_frame,
                playoff_combo: playoff_frame,
                unrequested_combo: unrequested_frame,
            },
        )

        result = asyncio.run(
            orch._discover_entities(
                discovery,
                ["2024-25"],
                bound_log,
                season_types=["Regular Season", "Playoffs"],
                include_players=False,
                include_teams=False,
                include_dates=False,
            )
        )

        artifacts = orch._discovery_artifacts()
        regular_cached = artifacts.load_frame(
            DiscoveryArtifactScope(
                kind="league_game_log",
                seasons=("2024-25",),
                season_types=("Regular Season",),
            )
        )
        assert regular_cached is not None
        assert regular_cached.to_dicts() == regular_frame.to_dicts()
        for season_type in ("Playoffs", "Pre Season"):
            assert (
                artifacts.load_frame(
                    DiscoveryArtifactScope(
                        kind="league_game_log",
                        seasons=("2024-25",),
                        season_types=(season_type,),
                    )
                )
                is None
            )
        assert (
            artifacts.load_frame(
                DiscoveryArtifactScope(
                    kind="league_game_log",
                    seasons=("2024-25",),
                    season_types=("Regular Season", "Playoffs"),
                )
            )
            is None
        )
        assert result[0] == ["regular"]
        assert result[4].to_dicts() == regular_frame.to_dicts()

    def test_require_complete_uses_caller_game_scope_not_result_declaration(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        regular_combo = ("2024-25", "Regular Season")
        regular_frame = pl.DataFrame({"game_id": ["regular"], "game_date": ["2024-10-22"]})
        discovery = AsyncMock()
        discovery.discover_game_ids_result.return_value = GameDiscoveryResult(
            game_ids=["regular"],
            raw=regular_frame,
            requested_combos=frozenset({regular_combo}),
            covered_combos=frozenset({regular_combo}),
            frames_by_combo={regular_combo: regular_frame},
        )

        with pytest.raises(InitDiscoveryCoverageError, match="missing season/season_type combos"):
            asyncio.run(
                orch._discover_entities(
                    discovery,
                    ["2024-25"],
                    bound_log,
                    season_types=["Regular Season", "Playoffs"],
                    include_players=False,
                    include_teams=False,
                    include_dates=False,
                    require_complete=True,
                )
            )

    def test_require_complete_rejects_declared_coverage_without_exact_frame(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        regular_combo = ("2024-25", "Regular Season")
        playoffs_combo = ("2024-25", "Playoffs")
        regular_frame = pl.DataFrame({"game_id": ["regular"], "game_date": ["2024-10-22"]})
        discovery = AsyncMock()
        discovery.discover_game_ids_result.return_value = GameDiscoveryResult(
            game_ids=["regular"],
            raw=regular_frame,
            requested_combos=frozenset({regular_combo, playoffs_combo}),
            covered_combos=frozenset({regular_combo, playoffs_combo}),
            frames_by_combo={regular_combo: regular_frame},
        )

        with pytest.raises(InitDiscoveryCoverageError, match="missing exact combo frames"):
            asyncio.run(
                orch._discover_entities(
                    discovery,
                    ["2024-25"],
                    bound_log,
                    season_types=["Regular Season", "Playoffs"],
                    include_players=False,
                    include_teams=False,
                    include_dates=False,
                    require_complete=True,
                )
            )

    def test_aggregate_game_cache_is_rebuilt_from_requested_exact_frames(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        regular_combo = ("2024-25", "Regular Season")
        playoffs_combo = ("2024-25", "Playoffs")
        unrequested_combo = ("2024-25", "Pre Season")
        regular_frame = pl.DataFrame({"game_id": ["regular"], "game_date": ["2024-10-22"]})
        playoffs_frame = pl.DataFrame({"game_id": ["playoff"], "game_date": ["2025-04-19"]})
        unrequested_frame = pl.DataFrame({"game_id": ["preseason"], "game_date": ["2024-10-04"]})
        discovery = AsyncMock()
        discovery.discover_game_ids_result.return_value = GameDiscoveryResult(
            game_ids=["regular", "playoff", "preseason"],
            raw=pl.concat([regular_frame, playoffs_frame, unrequested_frame]),
            requested_combos=frozenset({regular_combo, playoffs_combo}),
            covered_combos=frozenset({regular_combo, playoffs_combo, unrequested_combo}),
            frames_by_combo={
                regular_combo: regular_frame,
                playoffs_combo: playoffs_frame,
                unrequested_combo: unrequested_frame,
            },
        )

        asyncio.run(
            orch._discover_entities(
                discovery,
                ["2024-25"],
                bound_log,
                season_types=["Regular Season", "Playoffs"],
                include_players=False,
                include_teams=False,
                include_dates=False,
            )
        )

        cached = orch._discovery_artifacts().load_frame(
            DiscoveryArtifactScope(
                kind="league_game_log",
                seasons=("2024-25",),
                season_types=("Regular Season", "Playoffs"),
            )
        )
        assert cached is not None
        assert cached.to_dicts() == [*playoffs_frame.to_dicts(), *regular_frame.to_dicts()]

    def test_zero_row_historical_player_scope_forces_live_discovery(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        bound_log = MagicMock()
        artifacts = orch._discovery_artifacts()
        artifacts.upsert_ids(
            DiscoveryArtifactScope(
                kind="player_ids_all",
                seasons=("1946-47",),
                variant="historical",
            ),
            [],
            provenance="empty-test-cache",
        )
        artifacts.upsert_ids(
            DiscoveryArtifactScope(
                kind="player_ids_all",
                seasons=("1947-48",),
                variant="historical",
            ),
            [20],
            provenance="test-cache",
        )
        discovery = AsyncMock()
        discovery.discover_all_player_ids.return_value = [10, 20]

        _game_ids, player_ids, _team_ids, _game_dates, _game_log_df = asyncio.run(
            orch._discover_entities(
                discovery,
                ["1946-47", "1947-48"],
                bound_log,
                include_historical_players=True,
                include_games=False,
                include_players=True,
                include_teams=False,
                include_dates=False,
                require_complete=True,
            )
        )

        assert player_ids == [10, 20]
        discovery.discover_all_player_ids.assert_awaited_once_with(season=None)

    def test_current_team_refresh_bypasses_and_replaces_cached_inventory(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        artifacts = orch._discovery_artifacts()
        scope = DiscoveryArtifactScope(kind="current_team_ids", seasons=("2024-25",))
        artifacts.upsert_ids(scope, [1], provenance="stale-test-cache")
        discovery = AsyncMock()
        discovery.discover_current_team_ids.return_value = [1, 2]

        current_team_ids = asyncio.run(
            orch._discover_current_team_ids(
                discovery,
                seasons=["2024-25"],
                refresh=True,
            )
        )

        assert current_team_ids == [1, 2]
        assert artifacts.load_ids(scope) == [1, 2]
        discovery.discover_current_team_ids.assert_awaited_once()

    def test_historical_player_union_requires_exact_complete_season_results(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        discovery = AsyncMock()
        players_by_season = {
            "2023-24": [1, 2],
            "2024-25": [2, 3],
            "2025-26": [3, 4],
        }
        discovery.discover_all_player_ids_result.side_effect = lambda *, season: (
            _player_id_discovery_result(
                season,
                ids=players_by_season[season],
            )
        )

        player_ids = asyncio.run(
            orch._discover_complete_historical_player_union(
                discovery,
                seasons=["2023-24", "2024-25", "2025-26"],
            )
        )

        assert player_ids == [1, 2, 3, 4]
        assert [
            call.kwargs["season"]
            for call in discovery.discover_all_player_ids_result.await_args_list
        ] == ["2023-24", "2024-25", "2025-26"]
        discovery.discover_player_ids.assert_not_awaited()
        artifacts = orch._discovery_artifacts()
        assert artifacts.load_ids(
            DiscoveryArtifactScope(
                kind="player_ids_all",
                seasons=("2023-24", "2024-25", "2025-26"),
                variant="historical",
            )
        ) == [1, 2, 3, 4]

    def test_historical_player_union_rejects_any_inconclusive_season(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        discovery = AsyncMock()
        discovery.discover_all_player_ids_result.side_effect = [
            _player_id_discovery_result("2024-25", ids=[1]),
            PlayerIdDiscoveryResult(
                ids=[],
                requested_season="2025-26",
                source="common_all_players",
                failure_kind="transport",
            ),
        ]

        with pytest.raises(
            InitDiscoveryCoverageError,
            match="historical player discovery incomplete for 2025-26: transport",
        ):
            asyncio.run(
                orch._discover_complete_historical_player_union(
                    discovery,
                    seasons=["2024-25", "2025-26"],
                )
            )

        assert (
            orch._discovery_artifacts().load_ids(
                DiscoveryArtifactScope(
                    kind="player_ids_all",
                    seasons=("2024-25",),
                    variant="historical",
                )
            )
            == []
        )


class TestPlayerTeamWorkloadCache:
    def test_empty_exact_scope_skips_workload_persistence(self):
        orch = Orchestrator(settings=_mock_settings())

        with patch.object(orch, "_player_team_season_workloads") as store_factory:
            params = orch._persist_player_team_season_workloads(
                [],
                seasons=[],
                season_types=list(_ALL_SEASON_TYPES),
                covered_pairs=set(),
            )

        assert params == []
        store_factory.assert_not_called()

    def test_rows_without_exact_scope_fail_before_workload_persistence(self):
        orch = Orchestrator(settings=_mock_settings())

        with (
            patch.object(orch, "_player_team_season_workloads") as store_factory,
            pytest.raises(ValueError, match="require explicit covered"),
        ):
            orch._persist_player_team_season_workloads(
                [
                    {
                        "player_id": 1,
                        "team_id": 10,
                        "season": "2024-25",
                        "season_type": "Regular Season",
                    }
                ],
                seasons=["2024-25"],
                season_types=["Regular Season"],
                covered_pairs=set(),
            )

        store_factory.assert_not_called()

    def test_reuses_cache_when_every_requested_pair_is_explicitly_covered(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        store = orch._player_team_season_workloads()
        store.upsert(
            [],
            covered_pairs={("2024-25", "Regular Season")},
        )
        discovery = AsyncMock()

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=["2024-25"],
                season_types=["Regular Season"],
                run_mode="init",
            )
        )

        assert result.params == []
        assert result.requested_pairs == {("2024-25", "Regular Season")}
        assert result.covered_pairs == result.requested_pairs
        discovery.discover_player_team_season_params_result.assert_not_called()

    def test_cache_only_result_recomputes_upstream_unavailable_reasons(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        store = orch._player_team_season_workloads()
        covered_pairs = {
            ("1949-50", "All Star"),
            ("1998-99", "All Star"),
        }
        store.upsert(
            [],
            covered_pairs=covered_pairs,
        )
        discovery = AsyncMock()

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=["1949-50", "1998-99"],
                season_types=["All Star"],
            )
        )

        assert result.upstream_unavailable_pairs == {
            ("1949-50", "All Star"): ALL_STAR_PRE_HISTORY_UPSTREAM_UNAVAILABLE_REASON,
            ("1998-99", "All Star"): ALL_STAR_CANCELLED_UPSTREAM_UNAVAILABLE_REASON,
        }
        discovery.discover_player_team_season_params_result.assert_not_awaited()

    def test_live_result_preserves_upstream_unavailable_reason_evidence(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        pair = ("1998-99", "All Star")
        discovery = AsyncMock()
        discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=(pair[0],),
                season_types=(pair[1],),
                upstream_unavailable_pairs={pair: "live_attested_reason"},
            )
        )

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=[pair[0]],
                season_types=[pair[1]],
            )
        )

        assert result.upstream_unavailable_pairs == {pair: "live_attested_reason"}

    def test_partial_cache_retains_live_discovery_fallback(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        store = orch._player_team_season_workloads()
        store.upsert(
            [
                {
                    "player_id": 1,
                    "team_id": 10,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                }
            ],
            covered_pairs={("2024-25", "Regular Season")},
        )
        discovery = AsyncMock()
        live_result = _player_team_discovery_result(
            params=[
                {
                    "player_id": 2,
                    "team_id": 20,
                    "season": "2025-26",
                    "season_type": "Regular Season",
                }
            ],
            seasons=("2025-26",),
            season_types=("Regular Season",),
        )
        discovery.discover_player_team_season_params_result.return_value = live_result

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=["2024-25", "2025-26"],
                season_types=["Regular Season"],
            )
        )

        assert result.params == [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
        ]
        assert result.is_complete
        discovery.discover_player_team_season_params_result.assert_awaited_once_with(
            ["2025-26"],
            season_types=["Regular Season"],
        )

    def test_sparse_diagonal_cache_misses_fetch_only_exact_pairs(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        seasons = ["2024-25", "2025-26"]
        season_types = ["Regular Season", "Playoffs"]
        cached_pairs = {
            ("2024-25", "Playoffs"),
            ("2025-26", "Regular Season"),
        }
        store = orch._player_team_season_workloads()
        store.upsert(
            [
                {
                    "player_id": 1,
                    "team_id": 10,
                    "season": "2024-25",
                    "season_type": "Playoffs",
                },
                {
                    "player_id": 4,
                    "team_id": 40,
                    "season": "2025-26",
                    "season_type": "Regular Season",
                },
            ],
            covered_pairs=cached_pairs,
        )
        live_params = {
            ("2024-25", "Regular Season"): {
                "player_id": 2,
                "team_id": 20,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            ("2025-26", "Playoffs"): {
                "player_id": 3,
                "team_id": 30,
                "season": "2025-26",
                "season_type": "Playoffs",
            },
        }
        discovered_pair_calls: list[frozenset[tuple[str, str]]] = []

        async def discover_exact_pairs(
            requested_seasons: list[str],
            *,
            season_types: list[str],
        ) -> PlayerTeamSeasonDiscoveryResult:
            requested_pairs = frozenset(
                (season, season_type)
                for season in requested_seasons
                for season_type in season_types
            )
            discovered_pair_calls.append(requested_pairs)
            assert len(requested_pairs) == 1
            pair = next(iter(requested_pairs))
            return PlayerTeamSeasonDiscoveryResult(
                params=[live_params[pair]],
                requested_pairs=requested_pairs,
                covered_pairs=requested_pairs,
            )

        discovery = AsyncMock()
        discovery.discover_player_team_season_params_result.side_effect = discover_exact_pairs

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=seasons,
                season_types=season_types,
            )
        )

        assert result.is_complete
        assert {(param["season"], param["season_type"]) for param in result.params} == {
            *cached_pairs,
            *live_params,
        }
        assert discovered_pair_calls == [
            frozenset({("2024-25", "Regular Season")}),
            frozenset({("2025-26", "Playoffs")}),
        ]
        assert discovery.discover_player_team_season_params_result.await_count == 2

    def test_manifest_only_cache_retains_live_discovery_fallback(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        store = orch._player_team_season_workloads()
        store.upsert(
            [
                {
                    "player_id": 1,
                    "team_id": 10,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                }
            ],
            covered_pairs={("2024-25", "Regular Season")},
        )
        assert store.artifact_path is not None
        assert store.manifest_path is not None
        store.artifact_path.unlink()
        assert store.manifest_path.is_file()
        discovery = AsyncMock()
        live_result = _player_team_discovery_result(
            seasons=("2024-25",),
            season_types=("Regular Season",),
        )
        discovery.discover_player_team_season_params_result.return_value = live_result

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=["2024-25"],
                season_types=["Regular Season"],
            )
        )

        assert result == live_result
        discovery.discover_player_team_season_params_result.assert_awaited_once_with(
            ["2024-25"],
            season_types=["Regular Season"],
        )

    def test_parquet_only_cache_retains_live_discovery_fallback(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        store = orch._player_team_season_workloads()
        store.upsert(
            [],
            covered_pairs={("2024-25", "Regular Season")},
        )
        generation_path = store.artifact_path
        assert generation_path is not None
        assert store.manifest_path is not None
        store.manifest_path.unlink()
        assert generation_path.is_file()
        assert store.artifact_path is None
        discovery = AsyncMock()
        live_result = _player_team_discovery_result(
            seasons=("2024-25",),
            season_types=("Regular Season",),
        )
        discovery.discover_player_team_season_params_result.return_value = live_result

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=["2024-25"],
                season_types=["Regular Season"],
            )
        )

        assert result == live_result
        discovery.discover_player_team_season_params_result.assert_awaited_once_with(
            ["2024-25"],
            season_types=["Regular Season"],
        )

    def test_invalid_nonzero_cache_pair_forces_live_discovery(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        store = orch._player_team_season_workloads()
        store.upsert(
            [
                {
                    "player_id": 1,
                    "team_id": 10,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                }
            ],
            covered_pairs={("2024-25", "Regular Season")},
        )
        assert store.artifact_path is not None
        pl.read_parquet(store.artifact_path).head(0).write_parquet(store.artifact_path)
        discovery = AsyncMock()
        live_result = _player_team_discovery_result(
            params=[
                {
                    "player_id": 2,
                    "team_id": 20,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                }
            ],
            seasons=("2024-25",),
            season_types=("Regular Season",),
        )
        discovery.discover_player_team_season_params_result.return_value = live_result

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=["2024-25"],
                season_types=["Regular Season"],
                run_mode="init",
            )
        )

        assert result == live_result
        discovery.discover_player_team_season_params_result.assert_awaited_once_with(
            ["2024-25"],
            season_types=["Regular Season"],
        )

    @pytest.mark.parametrize("run_mode", ["daily", "monthly"])
    def test_refresh_modes_do_not_reuse_latest_season_cache(self, tmp_path, run_mode):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        store = orch._player_team_season_workloads()
        store.upsert(
            [
                {
                    "player_id": 1,
                    "team_id": 10,
                    "season": "2025-26",
                    "season_type": "Regular Season",
                }
            ],
            covered_pairs={("2025-26", "Regular Season")},
        )
        discovery = AsyncMock()
        live_result = _player_team_discovery_result(
            params=[
                {
                    "player_id": 2,
                    "team_id": 20,
                    "season": "2025-26",
                    "season_type": "Regular Season",
                }
            ],
            seasons=("2025-26",),
            season_types=("Regular Season",),
        )
        discovery.discover_player_team_season_params_result.return_value = live_result

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=["2025-26"],
                season_types=["Regular Season"],
                run_mode=run_mode,
            )
        )

        assert result == live_result
        discovery.discover_player_team_season_params_result.assert_awaited_once()

    def test_monthly_reuses_older_pair_and_refreshes_latest_pair(self, tmp_path):
        settings = _mock_settings()
        settings.duckdb_path = tmp_path / "nba.duckdb"
        orch = Orchestrator(settings=settings)
        store = orch._player_team_season_workloads()
        store.upsert(
            [
                {
                    "player_id": 1,
                    "team_id": 10,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                },
                {
                    "player_id": 2,
                    "team_id": 20,
                    "season": "2025-26",
                    "season_type": "Regular Season",
                },
            ],
            covered_pairs={
                ("2024-25", "Regular Season"),
                ("2025-26", "Regular Season"),
            },
        )
        discovery = AsyncMock()
        discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                params=[
                    {
                        "player_id": 3,
                        "team_id": 30,
                        "season": "2025-26",
                        "season_type": "Regular Season",
                    }
                ],
                seasons=("2025-26",),
                season_types=("Regular Season",),
            )
        )

        result = asyncio.run(
            orch._discover_player_team_season_result(
                discovery,
                seasons=["2024-25", "2025-26"],
                season_types=["Regular Season"],
                run_mode="monthly",
            )
        )

        assert result.params == [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 3,
                "team_id": 30,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
        ]
        assert result.is_complete
        discovery.discover_player_team_season_params_result.assert_awaited_once_with(
            ["2025-26"],
            season_types=["Regular Season"],
        )

    def test_incomplete_refresh_result_fails_closed(self):
        result = _player_team_discovery_result(
            seasons=("2025-26",),
            season_types=("Regular Season",),
            covered_pairs=frozenset(),
        )

        with pytest.raises(InitDiscoveryCoverageError, match="missing pairs"):
            Orchestrator._require_complete_player_team_discovery(result)


class TestPlayerSharding:
    def test_apply_player_shard_filters_by_discovery_order(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("NBADB_PLAYER_SHARD_INDEX", "1")
        monkeypatch.setenv("NBADB_PLAYER_SHARD_COUNT", "4")

        assert _apply_player_shard([100, 101, 102, 103, 104, 105, 106]) == [101, 105]

    def test_apply_player_shard_requires_complete_configuration(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("NBADB_PLAYER_SHARD_INDEX", "0")
        monkeypatch.delenv("NBADB_PLAYER_SHARD_COUNT", raising=False)

        with pytest.raises(ValueError, match="must both be set"):
            _apply_player_shard([100, 101])


# ---------------------------------------------------------------------------
# _init_db tests
# ---------------------------------------------------------------------------


class TestInitDb:
    def test_returns_cached_db(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        result_db, result_journal = orch._init_db()
        assert result_db is db
        assert result_journal is journal

    def test_creates_db_when_none(self):
        settings = _mock_settings()
        orch = Orchestrator(settings=settings)

        mock_db = MagicMock()
        mock_db.duckdb = MagicMock()
        mock_journal = MagicMock()
        with (
            patch(_DB_MANAGER, return_value=mock_db),
            patch(_JOURNAL, return_value=mock_journal),
        ):
            db, journal = orch._init_db()

        mock_db.init.assert_called_once()
        mock_journal.recover_interrupted_running.assert_called_once()
        assert orch._db is mock_db
        assert journal is mock_journal


# ---------------------------------------------------------------------------
# _transform_and_load tests
# ---------------------------------------------------------------------------


class TestTransformAndLoad:
    @pytest.mark.parametrize("transformers", [[], [SimpleNamespace(output_table="dim_game")]])
    def test_zero_or_partial_discovery_fails_before_pipeline(self, transformers):
        orch, db, journal = _build_orchestrator_with_mocks()

        with (
            patch(_TRANSFORMERS, return_value=transformers),
            patch(_PIPELINE) as mock_pipeline,
            pytest.raises(TransformerDiscoveryError, match="incomplete historical"),
        ):
            orch._transform_and_load(db, {}, journal)

        mock_pipeline.assert_not_called()

    def test_loads_non_empty_outputs(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        raw = {"stg_test": pl.DataFrame({"a": [1, 2]})}
        mock_outputs = {"dim_test": pl.DataFrame({"b": [3, 4, 5]})}

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = mock_outputs
        mock_loader = MagicMock()

        with (
            patch(_TRANSFORMERS, return_value=[]),
            patch(_VALIDATE_TRANSFORMERS),
            patch(_PIPELINE, return_value=mock_pipeline),
            patch(_LOADER, return_value=mock_loader),
            patch(_CURRENT_SEASON, return_value="2024-25"),
        ):
            tables, rows, failed = orch._transform_and_load(db, raw, journal)

        assert tables == 1
        assert rows == 3
        assert failed == 0
        mock_loader.load.assert_called_once()
        assert mock_pipeline.run.call_args.kwargs["validate_input_schemas"] is True
        assert mock_pipeline.run.call_args.kwargs["require_complete"] is False

    def test_skips_empty_outputs(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        raw = {"stg_test": pl.DataFrame({"a": [1]})}
        mock_outputs = {"dim_empty": pl.DataFrame()}

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = mock_outputs
        mock_loader = MagicMock()

        with (
            patch(_TRANSFORMERS, return_value=[]),
            patch(_VALIDATE_TRANSFORMERS),
            patch(_PIPELINE, return_value=mock_pipeline),
            patch(_LOADER, return_value=mock_loader),
            patch(_CURRENT_SEASON, return_value="2024-25"),
        ):
            tables, rows, failed = orch._transform_and_load(db, raw, journal)

        assert tables == 0
        assert rows == 0
        mock_loader.load.assert_not_called()
        assert mock_pipeline.run.call_args.kwargs["validate_input_schemas"] is True
        assert mock_pipeline.run.call_args.kwargs["require_complete"] is False

    def test_strict_mode_materializes_schema_valid_empty_outputs(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        raw = {"stg_test": pl.DataFrame({"a": [1]})}
        empty_output = pl.DataFrame(schema={"game_id": pl.String})
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = {"fact_empty": empty_output}
        mock_loader = MagicMock()

        with (
            patch(_TRANSFORMERS, return_value=[]),
            patch(_VALIDATE_TRANSFORMERS),
            patch(_PIPELINE, return_value=mock_pipeline),
            patch(_LOADER, return_value=mock_loader),
            patch(_CURRENT_SEASON, return_value="2024-25"),
        ):
            tables, rows, failed = orch._transform_and_load(
                db,
                raw,
                journal,
                require_complete_transforms=True,
                materialize_empty_outputs=True,
            )

        assert (tables, rows, failed) == (1, 0, 0)
        mock_pipeline.run.assert_called_once()
        assert mock_pipeline.run.call_args.kwargs["require_complete"] is True
        mock_loader.load.assert_called_once_with("fact_empty", empty_output, mode="replace")
        journal.set_watermark.assert_called_once_with(
            "fact_empty",
            "last_load",
            "2024-25",
            0,
        )
        journal.record_table_metadata.assert_called_once()
        assert journal.record_table_metadata.call_args.args[:2] == ("fact_empty", 0)

    def test_successor_strict_mode_selects_complete_live_transform_universe(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        pipeline = MagicMock()
        pipeline.run.return_value = {}

        with (
            patch(_TRANSFORMERS, return_value=[]) as discover,
            patch(_VALIDATE_TRANSFORMERS) as validate,
            patch(_PIPELINE, return_value=pipeline),
            patch(_LOADER, return_value=MagicMock()),
        ):
            assert orch._transform_and_load(
                db,
                {},
                journal,
                require_complete_transforms=True,
                materialize_empty_outputs=True,
                include_live_transforms=True,
            ) == (0, 0, 0)

        discover.assert_called_once_with(include_live=True)
        validate.assert_called_once_with([], include_live=True)

    def test_successor_watermark_uses_fixed_intent_season_without_wall_clock(
        self,
        tmp_path: Path,
    ) -> None:
        route = staging_route_contract_bundle().routes[0]
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters={},
            provider_authority_sha256=route.provider_authority_sha256,
        )
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=_mock_capture_session(),
            successor_transaction=candidate,
            **_successor_transform_scratch_kwargs(tmp_path),
        )
        db = MagicMock()
        journal = MagicMock()
        output = pl.DataFrame({"game_id": ["0022500001"]})
        pipeline = MagicMock()
        pipeline.run.return_value = {"fact_game": output}
        readback = (
            TransformOutputAttestation(
                table_name="fact_game",
                row_count=1,
                schema_sha256="1" * 64,
                content_sha256="2" * 64,
            ),
        )

        with (
            patch(_TRANSFORMERS, return_value=[SimpleNamespace(output_table="fact_game")]),
            patch(_VALIDATE_TRANSFORMERS),
            patch(_PIPELINE, return_value=pipeline),
            patch(_LOADER, return_value=MagicMock()),
            patch(_CURRENT_SEASON, side_effect=AssertionError("wall clock forbidden")),
            patch(
                "nbadb.orchestrate.orchestrator.build_successor_transform_attestations",
                return_value=readback,
            ),
        ):
            result = orch._transform_and_load(
                db,
                {},
                journal,
                require_complete_transforms=True,
                materialize_empty_outputs=True,
                include_live_transforms=True,
                successor_watermark_season="2025-26",
            )

        assert result == (1, 1, 0)
        journal.set_watermark.assert_called_once_with(
            "fact_game",
            "last_load",
            "2025-26",
            1,
        )

    def test_successor_attests_duckdb_readback_not_preload_frame(self, tmp_path: Path) -> None:
        route = staging_route_contract_bundle().routes[0]
        candidate = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters={},
            provider_authority_sha256=route.provider_authority_sha256,
        )
        scratch_kwargs = _successor_transform_scratch_kwargs(tmp_path)
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=_mock_capture_session(),
            successor_transaction=candidate,
            **scratch_kwargs,
        )
        db = MagicMock()
        journal = MagicMock()
        forged_preload = pl.DataFrame({"game_id": ["forged-preload-value"]})
        pipeline = MagicMock()
        pipeline.run.return_value = {"fact_game": forged_preload}
        readback = (
            TransformOutputAttestation(
                table_name="fact_game",
                row_count=1,
                schema_sha256="a" * 64,
                content_sha256="b" * 64,
            ),
        )

        with (
            patch(_TRANSFORMERS, return_value=[SimpleNamespace(output_table="fact_game")]),
            patch(_VALIDATE_TRANSFORMERS),
            patch(_PIPELINE, return_value=pipeline),
            patch(_LOADER, return_value=MagicMock()),
            patch(
                "nbadb.orchestrate.orchestrator.build_successor_transform_attestations",
                return_value=readback,
            ) as authority,
        ):
            result = orch._transform_and_load(
                db,
                {},
                journal,
                require_complete_transforms=True,
                materialize_empty_outputs=True,
                include_live_transforms=True,
                successor_watermark_season="2025-26",
            )

        assert result == (1, 1, 0)
        assert orch.transform_output_attestations == readback
        authority.assert_called_once_with(
            db.duckdb,
            scratch_parent=scratch_kwargs["successor_transform_scratch_parent"],
            expected_scratch_parent_identity=scratch_kwargs[
                "expected_successor_transform_scratch_identity"
            ],
            transform_scratch_max_bytes=scratch_kwargs["successor_transform_scratch_max_bytes"],
        )

    def test_strict_complete_load_records_exact_sorted_output_attestations(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        outputs = {
            "fact_z": pl.DataFrame({"game_id": ["0022400001"], "points": [20]}),
            "dim_a": pl.DataFrame(schema={"team_id": pl.Int64}),
        }
        transformers = [
            SimpleNamespace(output_table="fact_z"),
            SimpleNamespace(output_table="dim_a"),
        ]
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = outputs

        with (
            patch(_TRANSFORMERS, return_value=transformers),
            patch(_VALIDATE_TRANSFORMERS),
            patch(_PIPELINE, return_value=mock_pipeline),
            patch(_LOADER, return_value=MagicMock()),
            patch(_CURRENT_SEASON, return_value="2024-25"),
        ):
            result = orch._transform_and_load(
                db,
                {},
                journal,
                require_complete_transforms=True,
                materialize_empty_outputs=True,
            )

        assert result == (2, 1, 0)
        assert [item.table_name for item in orch.transform_output_attestations] == [
            "dim_a",
            "fact_z",
        ]
        assert [item.row_count for item in orch.transform_output_attestations] == [0, 1]
        assert all(len(item.schema_sha256) == 64 for item in orch.transform_output_attestations)
        assert all(len(item.content_sha256) == 64 for item in orch.transform_output_attestations)

    def test_strict_output_attestations_remain_empty_after_any_load_failure(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        outputs = {
            "dim_a": pl.DataFrame({"team_id": [1]}),
            "fact_z": pl.DataFrame({"game_id": ["0022400001"]}),
        }
        transformers = [
            SimpleNamespace(output_table="dim_a"),
            SimpleNamespace(output_table="fact_z"),
        ]
        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = outputs
        mock_loader = MagicMock()
        mock_loader.load.side_effect = [None, RuntimeError("load failed")]

        with (
            patch(_TRANSFORMERS, return_value=transformers),
            patch(_VALIDATE_TRANSFORMERS),
            patch(_PIPELINE, return_value=mock_pipeline),
            patch(_LOADER, return_value=mock_loader),
            patch(_CURRENT_SEASON, return_value="2024-25"),
        ):
            result = orch._transform_and_load(
                db,
                {},
                journal,
                require_complete_transforms=True,
                materialize_empty_outputs=True,
            )

        assert result == (1, 1, 1)
        assert orch.transform_output_attestations == ()

    def test_counts_load_failures(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        raw = {"stg_test": pl.DataFrame({"a": [1]})}
        mock_outputs = {"dim_fail": pl.DataFrame({"b": [1]})}

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = mock_outputs
        mock_loader = MagicMock()
        mock_loader.load.side_effect = RuntimeError("load failed")

        with (
            patch(_TRANSFORMERS, return_value=[]),
            patch(_VALIDATE_TRANSFORMERS),
            patch(_PIPELINE, return_value=mock_pipeline),
            patch(_LOADER, return_value=mock_loader),
            patch(_CURRENT_SEASON, return_value="2024-25"),
        ):
            tables, rows, failed = orch._transform_and_load(db, raw, journal)

        assert tables == 0
        assert failed == 1
        assert mock_pipeline.run.call_args.kwargs["validate_input_schemas"] is True


# ---------------------------------------------------------------------------
# _extract_all_patterns tests
# ---------------------------------------------------------------------------


class TestExtractAllPatterns:
    def test_persists_discovery_game_log_as_durable_chunk(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        runner.run_pattern_result = AsyncMock()
        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        persist_events: list[tuple[dict[str, pl.DataFrame], dict[str, object]]] = []

        def persist_results(frames: dict[str, pl.DataFrame], **metadata: object) -> None:
            persist_events.append((frames, metadata))

        outcome = asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=game_log_df,
                run_mode="daily",
                persist_results=persist_results,
            )
        )

        assert outcome.raw["stg_league_game_log"].equals(game_log_df)
        assert len(persist_events) == 1
        frames, metadata = persist_events[0]
        assert frames["stg_league_game_log"].equals(game_log_df)
        assert metadata["run_mode"] == "daily"
        assert metadata["pattern"] == "discovery"
        assert metadata["expected_staging_keys"] == ["stg_league_game_log"]
        assert metadata["materialize"] is False
        runner.run_pattern_result.assert_not_called()

    def test_forwards_expected_staging_keys_to_chunk_persistence(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        entry = SimpleNamespace(endpoint_name="ep1", param_pattern="season")
        persist_events: list[dict[str, object]] = []

        async def run_pattern_result(
            _pattern,
            _params,
            _entries,
            *,
            persist_chunk_results=None,
            **_kwargs,
        ):
            assert persist_chunk_results is not None
            persist_chunk_results(
                {},
                chunk_index=0,
                chunk_params=[{"season": "2024-25"}],
                expected_staging_keys=["stg_ep1"],
            )
            return PatternExtractionResult(eligible_calls=1, success_count=1, frames={})

        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[
                    ExtractionPlanItem(
                        label="season",
                        pattern="season",
                        entries=[entry],
                        params=[{"season": "2024-25"}],
                        priority=1,
                    )
                ],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="init",
                persist_results=lambda _frames, **metadata: persist_events.append(metadata),
            )
        )

        assert persist_events == [
            {
                "run_mode": "init",
                "lane_id": "season",
                "pattern": "season",
                "chunk_index": 0,
                "chunk_params": [{"season": "2024-25"}],
                "entries": [entry],
                "expected_staging_keys": ["stg_ep1"],
                "materialize": False,
            }
        ]

    def test_forwards_source_results_to_chunk_persistence(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        entry = SimpleNamespace(endpoint_name="ep1", param_pattern="season")
        source_results = [
            {
                "frames": {"stg_ep1": pl.DataFrame({"season": ["2024-25"]})},
                "source_endpoint_name": "ep1",
                "source_params_json": '{"season": "2024-25"}',
                "expected_staging_keys": ("stg_ep1",),
            }
        ]
        persist_events: list[dict[str, object]] = []

        async def run_pattern_result(
            _pattern,
            _params,
            _entries,
            *,
            persist_chunk_results=None,
            **_kwargs,
        ):
            assert persist_chunk_results is not None
            persist_chunk_results(
                {"stg_ep1": pl.DataFrame({"season": ["2024-25"]})},
                chunk_index=0,
                chunk_params=[{"season": "2024-25"}],
                expected_staging_keys=["stg_ep1"],
                source_results=source_results,
            )
            return PatternExtractionResult(
                eligible_calls=1,
                success_count=1,
                frames={"stg_ep1": pl.DataFrame({"season": ["2024-25"]})},
            )

        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[
                    ExtractionPlanItem(
                        label="season",
                        pattern="season",
                        entries=[entry],
                        params=[{"season": "2024-25"}],
                        priority=1,
                    )
                ],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="init",
                persist_results=lambda _frames, **metadata: persist_events.append(metadata),
            )
        )

        assert persist_events[0]["source_results"] is source_results

    def test_cume_foundation_precedes_exact_workload_dependent(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        runner._capture_contract_factory = object()
        item = _cume_player_plan_item()
        call_endpoints: list[str] = []
        receipt_sha256 = "a" * 64
        provider_sha256 = "b" * 64

        async def run_pattern_result(
            _pattern,
            params,
            entries,
            *,
            persist_chunk_results=None,
            **_kwargs,
        ):
            endpoint = entries[0].endpoint_name
            call_endpoints.append(endpoint)
            if endpoint == "cume_stats_player_games":
                route = "cume_stats_player_games:stg_cume_player_games:0"
                receipt = LogicalCallReceiptBinding(
                    logical_call_receipt_sha256=receipt_sha256,
                    endpoint_name=endpoint,
                    logical_parameters_sha256=canonical_parameters_sha256(params[0]),
                    provider_authority_sha256=provider_sha256,
                    result_route_ids=(route,),
                )
                frame = pl.DataFrame(
                    {
                        "matchup": ["GSW vs. LAL", "GSW @ LAL"],
                        "game_id": ["0022400001", "0022400002"],
                    }
                )
                assert persist_chunk_results is not None
                persist_chunk_results(
                    {"stg_cume_player_games": frame},
                    chunk_index=0,
                    chunk_params=params,
                    expected_staging_keys=["stg_cume_player_games"],
                    source_results=[
                        {
                            "frames": {"stg_cume_player_games": frame},
                            "source_endpoint_name": endpoint,
                            "source_params_json": json.dumps(params[0], sort_keys=True),
                            "expected_staging_keys": ("stg_cume_player_games",),
                            "receipt_binding": receipt,
                            "result_route_ids_by_staging_key": (("stg_cume_player_games", route),),
                        }
                    ],
                )
                return PatternExtractionResult(
                    frames={"stg_cume_player_games": frame},
                    eligible_calls=1,
                    success_count=1,
                    scheduled_calls=1,
                    row_count=2,
                )

            assert params[0]["player_id"] == 201939
            assert params[0]["game_ids"] == "0022400001|0022400002"
            assert len(params[0]["cume_workload_sha256"]) == 64
            assert params[0]["foundation_receipt_sha256"] == receipt_sha256
            assert params[0]["provider_authority_sha256"] == provider_sha256
            dependent_frame = pl.DataFrame({"person_id": [201939], "gp": [2]})
            return PatternExtractionResult(
                frames={"stg_cume_player": dependent_frame},
                eligible_calls=1,
                success_count=1,
                scheduled_calls=1,
                row_count=1,
            )

        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        outcome = asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[item],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="init",
            )
        )

        assert call_endpoints == ["cume_stats_player_games", "cume_stats_player"]
        assert outcome.pattern_failures == 0
        assert outcome.failed_calls == 0
        assert set(outcome.raw) == {"stg_cume_player_games", "stg_cume_player"}

    def test_cume_typed_zero_is_complete_and_schedules_no_dependent(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        runner._capture_contract_factory = object()
        item = _cume_player_plan_item()
        empty = pl.DataFrame(schema={"matchup": pl.String, "game_id": pl.String})
        receipt_sha256 = "a" * 64
        provider_sha256 = "b" * 64
        route = "cume_stats_player_games:stg_cume_player_games:0"

        async def run_pattern_result(
            _pattern,
            params,
            entries,
            *,
            persist_chunk_results=None,
            **_kwargs,
        ):
            assert entries[0].endpoint_name == "cume_stats_player_games"
            assert persist_chunk_results is not None
            receipt = LogicalCallReceiptBinding(
                logical_call_receipt_sha256=receipt_sha256,
                endpoint_name="cume_stats_player_games",
                logical_parameters_sha256=canonical_parameters_sha256(params[0]),
                provider_authority_sha256=provider_sha256,
                result_route_ids=(route,),
            )
            persist_chunk_results(
                {"stg_cume_player_games": empty},
                chunk_index=0,
                chunk_params=params,
                expected_staging_keys=["stg_cume_player_games"],
                source_results=[
                    {
                        "frames": {"stg_cume_player_games": empty},
                        "source_endpoint_name": "cume_stats_player_games",
                        "source_params_json": json.dumps(params[0], sort_keys=True),
                        "expected_staging_keys": ("stg_cume_player_games",),
                        "receipt_binding": receipt,
                        "result_route_ids_by_staging_key": (("stg_cume_player_games", route),),
                    }
                ],
            )
            return PatternExtractionResult(
                frames={},
                eligible_calls=1,
                success_count=1,
                scheduled_calls=1,
            )

        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        outcome = asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[item],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="init",
            )
        )

        runner.run_pattern_result.assert_awaited_once()
        assert outcome.pattern_failures == 0
        assert outcome.failed_calls == 0

    @pytest.mark.parametrize(
        ("game_ids", "expected_error"),
        [
            (["0022400001", "0022400001"], "duplicates"),
            (["224000001"], "ten-digit"),
            ([None], "staging schema"),
        ],
    )
    def test_cume_malformed_foundation_is_incomplete_and_never_runs_dependent(
        self,
        game_ids,
        expected_error,
    ):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        runner._capture_contract_factory = None
        item = _cume_player_plan_item()
        frame = pl.DataFrame(
            {
                "matchup": ["GSW vs. LAL"] * len(game_ids),
                "game_id": game_ids,
            },
            strict=False,
        )

        async def run_pattern_result(
            _pattern,
            params,
            _entries,
            *,
            persist_chunk_results=None,
            **_kwargs,
        ):
            assert persist_chunk_results is not None
            persist_chunk_results(
                {"stg_cume_player_games": frame},
                chunk_index=0,
                chunk_params=params,
                expected_staging_keys=["stg_cume_player_games"],
                source_results=[
                    {
                        "frames": {"stg_cume_player_games": frame},
                        "source_endpoint_name": "cume_stats_player_games",
                        "source_params_json": json.dumps(params[0], sort_keys=True),
                        "expected_staging_keys": ("stg_cume_player_games",),
                        "receipt_binding": None,
                        "result_route_ids_by_staging_key": (),
                    }
                ],
            )
            return PatternExtractionResult(
                frames={"stg_cume_player_games": frame},
                eligible_calls=1,
                success_count=1,
            )

        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        outcome = asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[item],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="init",
            )
        )

        runner.run_pattern_result.assert_awaited_once()
        assert outcome.pattern_failures == 1
        assert outcome.failed_calls == item.task_count
        assert expected_error in outcome.errors[0]

    def test_capture_required_cume_foundation_requires_exact_receipt_binding(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        runner._capture_contract_factory = object()
        item = _cume_player_plan_item()
        frame = pl.DataFrame({"matchup": ["GSW vs. LAL"], "game_id": ["0022400001"]})

        async def run_pattern_result(
            _pattern,
            params,
            _entries,
            *,
            persist_chunk_results=None,
            **_kwargs,
        ):
            assert persist_chunk_results is not None
            persist_chunk_results(
                {"stg_cume_player_games": frame},
                chunk_index=0,
                chunk_params=params,
                expected_staging_keys=["stg_cume_player_games"],
                source_results=[
                    {
                        "frames": {"stg_cume_player_games": frame},
                        "source_endpoint_name": "cume_stats_player_games",
                        "source_params_json": json.dumps(params[0], sort_keys=True),
                        "expected_staging_keys": ("stg_cume_player_games",),
                        "receipt_binding": None,
                        "result_route_ids_by_staging_key": (),
                    }
                ],
            )
            return PatternExtractionResult(
                frames={"stg_cume_player_games": frame},
                eligible_calls=1,
                success_count=1,
            )

        runner.run_pattern_result = AsyncMock(side_effect=run_pattern_result)

        outcome = asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[item],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="init",
            )
        )

        runner.run_pattern_result.assert_awaited_once()
        assert outcome.pattern_failures == 1
        assert "lacks a logical-call receipt" in outcome.errors[0]

    def test_cume_foundation_rejects_foreign_endpoint_receipt_binding(self):
        item = _cume_player_plan_item()
        foundation = item.entries[0]
        params = item.params[0]
        route = f"{foundation.endpoint_name}:{foundation.staging_key}:{foundation.result_set_index}"
        frame = pl.DataFrame({"matchup": ["GSW vs. LAL"], "game_id": ["0022400001"]})
        receipt = LogicalCallReceiptBinding(
            logical_call_receipt_sha256="a" * 64,
            endpoint_name="foreign_endpoint",
            logical_parameters_sha256=canonical_parameters_sha256(params),
            provider_authority_sha256="b" * 64,
            result_route_ids=(route,),
        )

        with pytest.raises(
            CumeWorkloadContractError,
            match="receipt does not bind the exact source scope and route",
        ):
            _derive_cume_workloads(
                item,
                [
                    {
                        "frames": {foundation.staging_key: frame},
                        "source_endpoint_name": foundation.endpoint_name,
                        "source_params_json": json.dumps(params, sort_keys=True),
                        "expected_staging_keys": (foundation.staging_key,),
                        "receipt_binding": receipt,
                        "result_route_ids_by_staging_key": ((foundation.staging_key, route),),
                    }
                ],
                capture_required=True,
            )

    def test_direct_cume_dependent_plan_is_rejected_before_runner(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        runner.run_pattern_result = AsyncMock()
        dependent = _cume_player_plan_item().cume_dependency
        assert dependent is not None
        direct_item = ExtractionPlanItem(
            label="unsafe direct cume",
            pattern="player_season",
            entries=list(dependent.dependent_entries),
            params=[
                {
                    "player_id": 201939,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                }
            ],
            priority=3,
        )

        with pytest.raises(
            ValueError,
            match="cannot bypass",
        ):
            asyncio.run(
                orch._extract_all_patterns(
                    runner,
                    plan=[direct_item],
                    seasons=[],
                    game_ids=[],
                    player_ids=[],
                    team_ids=[],
                    current_team_ids=[],
                    game_dates=[],
                    player_team_season_params=[],
                    game_log_df=pl.DataFrame(),
                )
            )

        runner.run_pattern_result.assert_not_awaited()

    def test_incomplete_pattern_result_surfaces_failed_calls(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        entry = SimpleNamespace(endpoint_name="ep1", param_pattern="season")
        runner.run_pattern_result = AsyncMock(
            return_value=PatternExtractionResult(
                frames={},
                eligible_calls=1,
                failure_count=1,
                errors=['ep1[{"season":"2024-25"}]: TimeoutError'],
            )
        )

        outcome = asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[
                    ExtractionPlanItem(
                        label="season",
                        pattern="season",
                        entries=[entry],
                        params=[{"season": "2024-25"}],
                        priority=1,
                    )
                ],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="daily",
            )
        )

        assert outcome.raw == {}
        assert outcome.pattern_failures == 1
        assert outcome.failed_calls == 1
        assert outcome.errors == ['ep1[{"season":"2024-25"}]: TimeoutError']

    def test_stale_progress_marker_does_not_skip_without_journal_evidence(self, tmp_path):
        orch, _db, journal = _build_orchestrator_with_mocks()
        journal.was_extracted_batch.return_value = set()
        runner = MagicMock()
        entry = SimpleNamespace(endpoint_name="ep1", param_pattern="season")
        item = ExtractionPlanItem(
            label="season",
            pattern="season",
            entries=[entry],
            params=[{"season": "2024-25"}],
            priority=1,
        )
        store = ExtractionProgressStore.from_duckdb_path(tmp_path / "planner.duckdb")
        key = store.slice_key("daily", item)
        store.mark_complete(
            key,
            task_count=1,
            eligible_calls=1,
            success_count=1,
            row_count=1,
            wall_time_seconds=1.0,
            staging_keys=["stg_ep1"],
            endpoint_families=["default"],
        )
        runner.run_pattern_result = AsyncMock(
            return_value=PatternExtractionResult(
                frames={"stg_ep1": pl.DataFrame({"season": ["2024-25"]})},
                eligible_calls=1,
                success_count=1,
            )
        )

        outcome = asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[item],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="daily",
                journal=journal,
                progress_store=store,
            )
        )

        runner.run_pattern_result.assert_awaited_once()
        assert "stg_ep1" in outcome.raw

    def test_progress_marker_skips_when_journal_evidence_matches(self, tmp_path):
        orch, _db, journal = _build_orchestrator_with_mocks()
        journal_key = ("ep1", '{"season": "2024-25"}')
        journal.was_extracted_batch.return_value = {journal_key}
        runner = MagicMock()
        runner.run_pattern_result = AsyncMock()
        entry = SimpleNamespace(endpoint_name="ep1", param_pattern="season")
        item = ExtractionPlanItem(
            label="season",
            pattern="season",
            entries=[entry],
            params=[{"season": "2024-25"}],
            priority=1,
        )
        store = ExtractionProgressStore.from_duckdb_path(tmp_path / "planner.duckdb")
        key = store.slice_key("daily", item)
        store.mark_complete(
            key,
            task_count=1,
            eligible_calls=1,
            success_count=1,
            row_count=1,
            wall_time_seconds=1.0,
            staging_keys=["stg_ep1"],
            endpoint_families=["default"],
        )

        outcome = asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[item],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="daily",
                journal=journal,
                progress_store=store,
            )
        )

        runner.run_pattern_result.assert_not_awaited()
        assert outcome.raw == {}

    def test_retry_skip_pattern_result_does_not_surface_failure(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        entry = SimpleNamespace(endpoint_name="ep1", param_pattern="season")
        runner.run_pattern_result = AsyncMock(
            return_value=PatternExtractionResult(
                frames={},
                eligible_calls=1,
                retry_skip_count=1,
            )
        )

        outcome = asyncio.run(
            orch._extract_all_patterns(
                runner,
                plan=[
                    ExtractionPlanItem(
                        label="season",
                        pattern="season",
                        entries=[entry],
                        params=[{"season": "2024-25"}],
                        priority=1,
                    )
                ],
                seasons=[],
                game_ids=[],
                player_ids=[],
                team_ids=[],
                current_team_ids=[],
                game_dates=[],
                player_team_season_params=[],
                game_log_df=pl.DataFrame(),
                run_mode="retry",
            )
        )

        assert outcome.pattern_failures == 0
        assert outcome.failed_calls == 0
        assert outcome.errors == []

    def test_patterns_run_in_priority_order(self):
        """Patterns execute in priority tiers: static/season before game."""
        orch, db, journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        call_order: list[str] = []

        async def track_pattern(pattern, params, entries, on_progress=None):
            call_order.append(pattern)
            return PatternExtractionResult(frames={})

        runner.run_pattern_result = AsyncMock(side_effect=track_pattern)

        static_entries = [MagicMock(endpoint_name="league_standings")]
        season_entries = [
            SimpleNamespace(
                endpoint_name="common_team_roster",
                season_type_capability="supported",
                supported_season_types=("Regular Season",),
                min_season=None,
            )
        ]
        game_entries = [MagicMock(endpoint_name="box_score_traditional")]

        def _entries(pattern: str):
            mapping = {
                "static": static_entries,
                "season": season_entries,
                "game": game_entries,
                "player": [],
                "team": [],
                "date": [],
                "player_season": [],
                "player_team_season": [],
                "team_season": [],
            }
            return mapping.get(pattern, [])

        player_team_season_params = [
            {
                "player_id": 201939,
                "team_id": 1610612744,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
        ]
        with patch(_GET_BY_PATTERN, side_effect=_entries):
            outcome = asyncio.run(
                orch._extract_all_patterns(
                    runner,
                    seasons=["2024-25"],
                    game_ids=["0022400001"],
                    player_ids=[],
                    team_ids=[],
                    game_dates=[],
                    player_team_season_params=player_team_season_params,
                    game_log_df=pl.DataFrame(),
                )
            )

        assert outcome.pattern_failures == 0
        # Static (tier 0) must come before season (tier 1) which must
        # come before game (tier 4)
        assert call_order.index("static") < call_order.index("season")
        assert call_order.index("season") < call_order.index("game")

    def test_extracts_player_team_season_cross_product_patterns(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        runner.run_pattern_result = AsyncMock(return_value=PatternExtractionResult(frames={}))

        player_season_entries = [
            SimpleNamespace(
                endpoint_name="player_game_log",
                season_type_capability="supported",
                supported_season_types=("Regular Season",),
                min_season=None,
            )
        ]
        player_team_season_entries = [
            SimpleNamespace(
                endpoint_name="video_details",
                season_type_capability="supported",
                supported_season_types=("Regular Season",),
                min_season=None,
            )
        ]
        team_season_entries = [
            SimpleNamespace(
                endpoint_name="team_game_log",
                season_type_capability="supported",
                supported_season_types=("Regular Season",),
                min_season=None,
            )
        ]

        def _entries(pattern: str):
            mapping = {
                "static": [],
                "season": [],
                "game": [],
                "player": [],
                "team": [],
                "date": [],
                "player_season": player_season_entries,
                "player_team_season": player_team_season_entries,
                "team_season": team_season_entries,
            }
            return mapping.get(pattern, [])

        player_team_season_params = [
            {
                "player_id": 201939,
                "team_id": 1610612744,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 2544,
                "team_id": 1610612747,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
        ]
        with patch(_GET_BY_PATTERN, side_effect=_entries):
            outcome = asyncio.run(
                orch._extract_all_patterns(
                    runner,
                    seasons=["2024-25", "2025-26"],
                    game_ids=[],
                    player_ids=[201939, 2544],
                    team_ids=[1610612744],
                    game_dates=[],
                    player_team_season_params=player_team_season_params,
                    game_log_df=pl.DataFrame(),
                )
            )

        assert outcome.pattern_failures == 0
        assert outcome.raw == {}
        runner.run_pattern_result.assert_any_await(
            "player_season",
            [
                {
                    "player_id": 201939,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                },
                {
                    "player_id": 201939,
                    "season": "2025-26",
                    "season_type": "Regular Season",
                },
                {
                    "player_id": 2544,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                },
                {
                    "player_id": 2544,
                    "season": "2025-26",
                    "season_type": "Regular Season",
                },
            ],
            player_season_entries,
            on_progress=None,
        )
        runner.run_pattern_result.assert_any_await(
            "team_season",
            [
                {
                    "team_id": 1610612744,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                },
                {
                    "team_id": 1610612744,
                    "season": "2025-26",
                    "season_type": "Regular Season",
                },
            ],
            team_season_entries,
            on_progress=None,
        )
        runner.run_pattern_result.assert_any_await(
            "player_team_season",
            [
                {**params, "context_measure": context_measure}
                for params in player_team_season_params
                for context_measure in VIDEO_CONTEXT_MEASURES
            ],
            player_team_season_entries,
            on_progress=None,
        )


# ---------------------------------------------------------------------------
# run_init tests
# ---------------------------------------------------------------------------


class TestRunInit:
    def test_run_init_returns_pipeline_result(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2024-10-22"]}),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_all_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_current_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(season_types=_ALL_SEASON_TYPES)
        )

        mock_runner = _mock_runner()

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_persist_staging_to_duckdb"),
            patch.object(orch, "_materialize_staging_batches"),
            patch.object(
                orch,
                "_load_staging_from_duckdb",
                return_value={"stg_league_game_log": pl.DataFrame({"game_id": ["0022400001"]})},
            ),
            patch.object(orch, "_transform_and_load", return_value=(2, 100, 0)),
        ):
            result = asyncio.run(orch.run_init())

        assert isinstance(result, PipelineResult)
        assert result.tables_updated == 2
        assert result.rows_total == 100
        assert result.duration_seconds > 0

    def test_run_init_resumes_when_journal_has_done_entries(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.has_done_entries.return_value = True

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2024-10-22"]}),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_all_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_current_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(season_types=_ALL_SEASON_TYPES)
        )

        mock_runner = _mock_runner()

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_persist_staging_to_duckdb"),
            patch.object(orch, "_materialize_staging_batches"),
            patch.object(
                orch,
                "_load_staging_from_duckdb",
                return_value={"stg_league_game_log": pl.DataFrame({"game_id": ["0022400001"]})},
            ),
            patch.object(orch, "_transform_and_load", return_value=(2, 100, 0)),
        ):
            asyncio.run(orch.run_init())

        # Journal should NOT be cleared — resume skips done entries
        journal.clear_journal.assert_not_called()

    def test_run_init_loads_persisted_staging_when_resume_only_has_discovery_seed(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.has_done_entries.return_value = True

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2024-10-22"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_all_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_current_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(season_types=_ALL_SEASON_TYPES)
        )

        recovered_raw = {"stg_box_score_traditional": pl.DataFrame({"game_id": ["0022400001"]})}
        mock_runner = _mock_runner(planned_calls=3, skipped=3, skipped_due_to_journal=3)
        mock_extract = AsyncMock(
            return_value=ExtractionOutcome(raw={"stg_league_game_log": game_log_df})
        )

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(
                orch, "_load_staging_from_duckdb", return_value=recovered_raw
            ) as mock_load,
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)) as mock_transform,
        ):
            result = asyncio.run(orch.run_init())

        mock_load.assert_called_once_with(db)
        assert mock_transform.call_args.args[1] is recovered_raw
        assert result.tables_updated == 1

    def test_run_init_stops_before_phase_b_after_current_run_failures(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.has_done_entries.return_value = True

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2024-10-22"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_all_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_current_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(season_types=_ALL_SEASON_TYPES)
        )

        mock_runner = _mock_runner(
            planned_calls=3,
            skipped=2,
            skipped_due_to_journal=2,
            failed_current_run=1,
        )
        mock_extract = AsyncMock(
            return_value=ExtractionOutcome(
                raw={"stg_league_game_log": game_log_df},
                pattern_failures=0,
                failed_calls=1,
                errors=['box_score_traditional[{"game_id":"0022400001"}]: TransientError'],
            )
        )

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(
                orch,
                "_load_staging_from_duckdb",
                return_value={"stg_league_game_log": game_log_df},
            ) as mock_load,
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)) as mock_transform,
        ):
            result = asyncio.run(orch.run_init())

        mock_load.assert_not_called()
        mock_transform.assert_not_called()
        assert result.failed_extractions == 1
        assert result.tables_updated == 0


class TestPersistStagingToDuckdb:
    def test_source_parameter_binding_dto_requires_exact_pair_without_fallback(self):
        from nbadb.contracts.logical_provider_parameter_binding import (
            LogicalProviderParameterBindingV1,
        )
        from tests.unit.contracts.test_raw_request_finalization import (
            _aliased_stats_case,
        )

        _snapshot, _binding, _receipts, parameter_binding = _aliased_stats_case()
        assert _source_logical_provider_parameter_authority({}) == (None, None)
        carried = {
            "logical_provider_parameter_binding": parameter_binding,
            "expected_logical_provider_parameter_binding_sha256": (
                parameter_binding.binding_sha256
            ),
        }
        observed_binding, observed_pin = _source_logical_provider_parameter_authority(carried)
        assert type(observed_binding) is LogicalProviderParameterBindingV1
        assert observed_binding is parameter_binding
        assert observed_pin == parameter_binding.binding_sha256

        for one_sided in (
            {"logical_provider_parameter_binding": parameter_binding},
            {
                "expected_logical_provider_parameter_binding_sha256": (
                    parameter_binding.binding_sha256
                )
            },
        ):
            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="parameter binding is one-sided",
            ):
                _source_logical_provider_parameter_authority(one_sided)

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="parameter binding has a foreign shape",
        ):
            _source_logical_provider_parameter_authority(
                {
                    "logical_provider_parameter_binding": object(),
                    "expected_logical_provider_parameter_binding_sha256": "f" * 64,
                }
            )

    def test_parameter_binding_finalization_rejects_missing_and_swapped_authority(self):
        from nbadb.contracts.logical_provider_parameter_binding import (
            LogicalProviderParameterBindingV1,
        )
        from nbadb.contracts.raw_request_finalization import (
            RawRequestFinalizationError,
            finalize_raw_request_capture,
        )
        from tests.unit.contracts.test_raw_request_finalization import (
            _aliased_stats_case,
        )

        snapshot, binding, receipts, parameter_binding = _aliased_stats_case()
        with pytest.raises(
            RawRequestFinalizationError,
            match="differ but lack their independently pinned binding",
        ):
            finalize_raw_request_capture(snapshot, binding, receipts)

        exact = finalize_raw_request_capture(
            snapshot,
            binding,
            receipts,
            logical_provider_parameter_binding=parameter_binding,
            expected_logical_provider_parameter_binding_sha256=(parameter_binding.binding_sha256),
        )
        assert (
            exact.observations[0].logical_provider_parameter_binding_sha256
            == parameter_binding.binding_sha256
        )

        swapped = LogicalProviderParameterBindingV1.build(
            logical_endpoint_name=parameter_binding.logical_endpoint_name,
            logical_parameters_sha256="f" * 64,
            result_route_ids=parameter_binding.result_route_ids,
            provider_entries=parameter_binding.provider_entries,
        )
        with pytest.raises(
            RawRequestFinalizationError,
            match="differs from the logical call",
        ):
            finalize_raw_request_capture(
                snapshot,
                binding,
                receipts,
                logical_provider_parameter_binding=swapped,
                expected_logical_provider_parameter_binding_sha256=(swapped.binding_sha256),
            )

    def test_raw_persistence_transports_pair_or_absence_to_finalization(
        self,
        tmp_path: Path,
    ) -> None:
        from tests.unit.contracts.test_raw_request_finalization import (
            _aliased_stats_case,
        )
        from tests.unit.orchestrate.test_raw_request_orchestrator_integration import (
            _db,
            _orchestrator,
            _request_closure,
            _stats_success_source,
        )

        class _FinalizationReachedError(RuntimeError):
            pass

        _snapshot, _binding, _receipts, parameter_binding = _aliased_stats_case()
        for carries_parameter_binding in (False, True):
            connection = duckdb.connect(":memory:")
            w2_root = tmp_path / ("bound" if carries_parameter_binding else "direct")
            w2_root.mkdir()
            orchestrator = _orchestrator(w2_root=w2_root)
            frames, source, _source_snapshot, _source_binding = _stats_success_source()
            if carries_parameter_binding:
                source["logical_provider_parameter_binding"] = parameter_binding
                source["expected_logical_provider_parameter_binding_sha256"] = (
                    parameter_binding.binding_sha256
                )
            finalizer = MagicMock(side_effect=_FinalizationReachedError)
            try:
                with (
                    patch(
                        "nbadb.contracts.raw_request_finalization.finalize_raw_request_capture",
                        finalizer,
                    ),
                    pytest.raises(_FinalizationReachedError),
                ):
                    orchestrator._persist_staging_to_duckdb(
                        _db(connection),
                        frames,
                        run_mode="init",
                        lane_id="lane",
                        pattern="season",
                        chunk_index=0,
                        chunk_params=[{"season": "2024-25"}],
                        entries=[],
                        source_results=[source],
                        request_closure_authority=_request_closure(),
                        materialize=False,
                    )
            finally:
                connection.close()

            assert finalizer.call_count == 1
            forwarded = finalizer.call_args.kwargs
            if carries_parameter_binding:
                assert forwarded["logical_provider_parameter_binding"] is parameter_binding
                assert (
                    forwarded["expected_logical_provider_parameter_binding_sha256"]
                    == parameter_binding.binding_sha256
                )
            else:
                assert forwarded["logical_provider_parameter_binding"] is None
                assert forwarded["expected_logical_provider_parameter_binding_sha256"] is None

    @pytest.mark.xfail(
        strict=True,
        reason="live request-closure authority is intentionally not implemented",
    )
    def test_successor_live_no_active_scoreboard_closes_as_typed_zero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        calls = (("live_score_board", {}),)
        scopes = _live_scopes(calls)
        provider_authority = (
            staging_route_contract_bundle()
            .by_route_id[scopes[0].route_id]
            .provider_authority_sha256
        )
        transaction = _successor_candidate_for_scopes(
            scopes=scopes,
            provider_authority_sha256=provider_authority,
        )
        session = _mock_capture_session()
        live_kwargs, raw_context_factory, plan_factory = _live_w2_fixture(tmp_path)
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=transaction,
            **live_kwargs,
        )
        orch._journal = MagicMock(spec=PipelineJournal)
        orch._journal.was_extracted.return_value = False
        orch._successor_execution_plan = _successor_plan_for_scopes(scopes)
        extraction = _exact_live_extraction(
            monkeypatch,
            tmp_path,
            game_ids=(),
            raw_context_factory=raw_context_factory,
            plan_factory=plan_factory,
        )
        source_call = extraction.source_calls[0]
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        persisted_before_completion: list[tuple[int, int]] = []

        def record_completed(_binding: LogicalCallReceiptBinding) -> None:
            persisted_before_completion.append(
                (
                    conn.execute("SELECT count(*) FROM _staging_chunk_journal").fetchone()[0],
                    conn.execute(
                        "SELECT count(*) FROM _successor_staging_replacement_journal"
                    ).fetchone()[0],
                )
            )

        session.record_completed.side_effect = record_completed
        try:
            with patch.object(
                orch,
                "_extract_successor_live_snapshot",
                return_value=extraction,
            ):
                result = orch._persist_successor_live_snapshot(db, run_mode="daily")
        finally:
            conn.close()

        assert result is extraction
        assert persisted_before_completion == [(1, 1)]
        assert len(orch.successor_delta_receipts) == 1
        receipt = orch.successor_delta_receipts[0]
        assert receipt.disposition is DeltaDisposition.TYPED_ZERO
        assert receipt.persisted_row_count == 0
        assert receipt.typed_zero_reason_code == "provider_success_empty"
        session.record_completed.assert_called_once_with(source_call.receipt_binding)

    @pytest.mark.xfail(
        strict=True,
        reason="live request-closure authority is intentionally not implemented",
    )
    def test_successor_live_active_calls_each_close_after_route_replacement(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        calls = (
            ("live_score_board", {}),
            ("live_odds", {}),
            ("live_play_by_play", {"game_id": "0022400001"}),
            ("live_box_score", {"game_id": "0022400001"}),
            ("live_play_by_play", {"game_id": "0022400002"}),
            ("live_box_score", {"game_id": "0022400002"}),
        )
        scopes = _live_scopes(calls)
        provider_authority = (
            staging_route_contract_bundle()
            .by_route_id[scopes[0].route_id]
            .provider_authority_sha256
        )
        transaction = _successor_candidate_for_scopes(
            scopes=scopes,
            provider_authority_sha256=provider_authority,
        )
        session = _mock_capture_session()
        live_kwargs, raw_context_factory, plan_factory = _live_w2_fixture(tmp_path)
        orch = Orchestrator(
            settings=_mock_settings(),
            capture_session=session,
            successor_transaction=transaction,
            **live_kwargs,
        )
        orch._journal = MagicMock(spec=PipelineJournal)
        orch._journal.was_extracted.return_value = False
        orch._successor_execution_plan = _successor_plan_for_scopes(scopes)
        extraction = _exact_live_extraction(
            monkeypatch,
            tmp_path,
            game_ids=("0022400001", "0022400002"),
            raw_context_factory=raw_context_factory,
            plan_factory=plan_factory,
        )
        source_calls = extraction.source_calls
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        replacement_counts: list[int] = []

        def record_completed(_binding: LogicalCallReceiptBinding) -> None:
            replacement_counts.append(
                conn.execute(
                    "SELECT count(*) FROM _successor_staging_replacement_journal"
                ).fetchone()[0]
            )

        session.record_completed.side_effect = record_completed
        try:
            with patch.object(
                orch,
                "_extract_successor_live_snapshot",
                return_value=extraction,
            ):
                result = orch._persist_successor_live_snapshot(db, run_mode="monthly")
        finally:
            conn.close()

        assert result is extraction
        assert replacement_counts == [1, 2, 3, 10, 11, 18]
        assert len(orch.successor_delta_receipts) == 18
        assert all(
            receipt.disposition is DeltaDisposition.OBSERVED
            for receipt in orch.successor_delta_receipts
        )
        assert session.record_completed.call_count == 6
        completed = [call.args[0] for call in session.record_completed.call_args_list]
        assert completed == [source_call.receipt_binding for source_call in source_calls]

    def test_persist_staging_appends_without_replacing_existing_rows(self):
        orch = Orchestrator(settings=_mock_settings())
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)

        try:
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [1]})},
            )
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": pl.DataFrame({"game_id": ["001", "002"], "value": [1, 2]})},
            )

            rows = conn.execute("SELECT game_id, value FROM stg_sample ORDER BY game_id").fetchall()
        finally:
            conn.close()

        assert rows == [("001", 1), ("002", 2)]

    def test_persist_staging_preserves_duplicate_rows(self):
        orch = Orchestrator(settings=_mock_settings())
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)

        try:
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": pl.DataFrame({"game_id": ["001", "001"], "value": [1, 1]})},
            )
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": pl.DataFrame({"game_id": ["001", "001"], "value": [1, 1]})},
            )

            rows = conn.execute("SELECT game_id, value FROM stg_sample ORDER BY game_id").fetchall()
        finally:
            conn.close()

        assert rows == [("001", 1), ("001", 1)]

    def test_persist_staging_uses_source_results_for_stable_ids(self):
        orch = Orchestrator(settings=_mock_settings())
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        frame = pl.DataFrame({"game_id": ["001"], "value": [1]})

        try:
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": frame},
                run_mode="init",
                lane_id="init.season.a",
                pattern="season",
                chunk_index=0,
                chunk_params=[{"season": "2024-25"}, {"season": "2025-26"}],
                entries=[SimpleNamespace(endpoint_name="ep1")],
                expected_staging_keys=["stg_sample"],
                source_results=[
                    {
                        "frames": {"stg_sample": frame},
                        "source_endpoint_name": "ep1",
                        "source_params_json": '{"season": "2024-25"}',
                        "expected_staging_keys": ("stg_sample",),
                    }
                ],
                materialize=False,
            )
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": frame},
                run_mode="init",
                lane_id="init.season.b",
                pattern="season",
                chunk_index=1,
                chunk_params=[{"season": "2024-25"}],
                entries=[SimpleNamespace(endpoint_name="ep1")],
                expected_staging_keys=["stg_sample"],
                source_results=[
                    {
                        "frames": {"stg_sample": frame},
                        "source_endpoint_name": "ep1",
                        "source_params_json": '{"season": "2024-25"}',
                        "expected_staging_keys": ("stg_sample",),
                    }
                ],
                materialize=False,
            )
            StagingBatchStore(conn).materialize(["stg_sample"])
            rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
            journal_count = conn.execute(
                "SELECT count(*) FROM _staging_chunk_journal WHERE staging_key = 'stg_sample'"
            ).fetchone()[0]
        finally:
            conn.close()

        assert rows == [("001", 1)]
        assert journal_count == 1

    def test_persist_staging_binds_logical_receipt_to_source_route(self):
        orch = Orchestrator(settings=_mock_settings())
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        params = {"season": "2024-25"}
        route = "ep1:stg_sample:0"
        binding = LogicalCallReceiptBinding(
            logical_call_receipt_sha256="a" * 64,
            endpoint_name="ep1",
            logical_parameters_sha256=canonical_parameters_sha256(params),
            provider_authority_sha256="c" * 64,
            result_route_ids=(route,),
        )
        try:
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": pl.DataFrame({"value": [1]})},
                run_mode="init",
                pattern="season",
                source_results=[
                    {
                        "frames": {"stg_sample": pl.DataFrame({"value": [1]})},
                        "source_endpoint_name": "ep1",
                        "source_params_json": '{"season": "2024-25"}',
                        "expected_staging_keys": ("stg_sample",),
                        "receipt_binding": binding,
                        "result_route_ids_by_staging_key": (("stg_sample", route),),
                    }
                ],
                materialize=False,
            )
            row = conn.execute(
                """
                SELECT logical_call_receipt_sha256,
                       provider_authority_sha256,
                       logical_parameters_sha256,
                       result_route_id,
                       persisted_row_count
                FROM _staging_chunk_journal
                """
            ).fetchone()
        finally:
            conn.close()

        assert row == (
            binding.logical_call_receipt_sha256,
            binding.provider_authority_sha256,
            binding.logical_parameters_sha256,
            route,
            1,
        )

    def test_capture_records_completion_only_after_durable_staging_persistence(self):
        session = _mock_capture_session()
        orch = Orchestrator(settings=_mock_settings(), capture_session=session)
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        params = {"season": "2024-25"}
        route = "ep1:stg_sample:0"
        binding = LogicalCallReceiptBinding(
            logical_call_receipt_sha256="a" * 64,
            endpoint_name="ep1",
            logical_parameters_sha256=canonical_parameters_sha256(params),
            provider_authority_sha256="c" * 64,
            result_route_ids=(route,),
        )
        observed: list[tuple[LogicalCallReceiptBinding, int]] = []

        def record_completed(completed: LogicalCallReceiptBinding) -> None:
            persisted = conn.execute("SELECT count(*) FROM _staging_chunk_journal").fetchone()[0]
            observed.append((completed, persisted))

        session.record_completed.side_effect = record_completed
        try:
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": pl.DataFrame({"value": [1]})},
                run_mode="init",
                pattern="season",
                source_results=[
                    {
                        "frames": {"stg_sample": pl.DataFrame({"value": [1]})},
                        "source_endpoint_name": "ep1",
                        "source_params_json": '{"season": "2024-25"}',
                        "expected_staging_keys": ("stg_sample",),
                        "receipt_binding": binding,
                        "result_route_ids_by_staging_key": (("stg_sample", route),),
                    }
                ],
                materialize=False,
            )
        finally:
            conn.close()

        assert observed == [(binding, 1)]

    def test_successor_persistence_emits_exact_intent_bound_delta_receipt(self):
        route = staging_route_contract_bundle().routes[0]
        params = {"season": "2024-25"}
        params_json = json.dumps(params, sort_keys=True)
        scope_sha256 = canonical_parameters_sha256(params)
        prior_binding = LogicalCallReceiptBinding(
            logical_call_receipt_sha256="a" * 64,
            endpoint_name=route.endpoint_name,
            logical_parameters_sha256=scope_sha256,
            provider_authority_sha256=route.provider_authority_sha256,
            result_route_ids=(route.route_id,),
        )
        fresh_binding = LogicalCallReceiptBinding(
            logical_call_receipt_sha256="d" * 64,
            endpoint_name=route.endpoint_name,
            logical_parameters_sha256=scope_sha256,
            provider_authority_sha256=route.provider_authority_sha256,
            result_route_ids=(route.route_id,),
        )
        transaction = _successor_candidate(
            route_id=route.route_id,
            route_contract_sha256=route.contract_sha256,
            parameters=params,
            provider_authority_sha256=route.provider_authority_sha256,
        )
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        prior_frame = pl.DataFrame({"value": [1]})
        fresh_frame = pl.DataFrame({"value": [2]})
        source_identity = {
            "source_endpoint_name": route.endpoint_name,
            "source_params_json": params_json,
            "expected_staging_keys": (route.staging_key,),
            "result_route_ids_by_staging_key": ((route.staging_key, route.route_id),),
        }
        try:
            baseline_orch = Orchestrator(settings=_mock_settings())
            baseline_orch._persist_staging_to_duckdb(
                db,
                {route.staging_key: prior_frame},
                run_mode="init",
                pattern=route.param_pattern,
                source_results=[
                    {
                        **source_identity,
                        "frames": {route.staging_key: prior_frame},
                        "receipt_binding": prior_binding,
                    }
                ],
                materialize=False,
            )

            session = _mock_capture_session()
            orch = Orchestrator(
                settings=_mock_settings(),
                capture_session=session,
                successor_transaction=transaction,
            )
            orch._successor_execution_plan = _successor_plan_for_scopes(
                transaction.intent.requested_scopes
            )
            orch._persist_staging_to_duckdb(
                db,
                {route.staging_key: fresh_frame},
                run_mode="daily",
                pattern=route.param_pattern,
                source_results=[
                    {
                        **source_identity,
                        "frames": {route.staging_key: fresh_frame},
                        "receipt_binding": fresh_binding,
                    }
                ],
                materialize=False,
            )
            stored_generation = conn.execute(
                """
                SELECT successor_generation_sha256
                FROM _successor_staging_replacement_journal
                """
            ).fetchone()[0]
        finally:
            conn.close()

        assert stored_generation == transaction.generation_identity_sha256
        assert len(orch.successor_delta_receipts) == 1
        receipt = orch.successor_delta_receipts[0]
        assert (
            receipt.requested_scope_sha256 == transaction.intent.requested_scopes[0].identity_sha256
        )
        assert receipt.logical_call_receipt_sha256 == fresh_binding.logical_call_receipt_sha256
        assert receipt.prior_persisted_content_sha256 == frame_content_hash(prior_frame)
        binding = orch._successor_execution_plan.planned_route_replacement_bindings[0]
        assert receipt.execution_dispatch_identity_sha256 == (
            binding.execution_dispatch_identity_sha256
        )
        assert receipt.planning_dependency_identity_sha256s == (
            binding.planning_dependency_identity_sha256s
        )
        session.record_completed.assert_called_once_with(fresh_binding)

    def test_capture_required_persistence_rejects_missing_completion_binding(self):
        session = _mock_capture_session()
        orch = Orchestrator(settings=_mock_settings(), capture_session=session)
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        try:
            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="durable staging success lacks a logical-call receipt",
            ):
                orch._persist_staging_to_duckdb(
                    db,
                    {"stg_sample": pl.DataFrame({"value": [1]})},
                    source_results=[
                        {
                            "frames": {"stg_sample": pl.DataFrame({"value": [1]})},
                            "source_endpoint_name": "ep1",
                            "source_params_json": '{"season": "2024-25"}',
                            "expected_staging_keys": ("stg_sample",),
                            "receipt_binding": None,
                            "result_route_ids_by_staging_key": (),
                        }
                    ],
                    materialize=False,
                )
            assert conn.execute("SELECT count(*) FROM _staging_chunk_journal").fetchone()[0] == 1
        finally:
            conn.close()

        session.record_completed.assert_not_called()

    def test_persist_staging_rejects_receipt_parameter_mismatch(self):
        orch = Orchestrator(settings=_mock_settings())
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        route = "ep1:stg_sample:0"
        binding = LogicalCallReceiptBinding(
            logical_call_receipt_sha256="a" * 64,
            endpoint_name="ep1",
            logical_parameters_sha256=canonical_parameters_sha256({"season": "2025-26"}),
            provider_authority_sha256="c" * 64,
            result_route_ids=(route,),
        )
        try:
            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="parameters do not match",
            ):
                orch._persist_staging_to_duckdb(
                    db,
                    {"stg_sample": pl.DataFrame({"value": [1]})},
                    source_results=[
                        {
                            "frames": {"stg_sample": pl.DataFrame({"value": [1]})},
                            "source_endpoint_name": "ep1",
                            "source_params_json": '{"season": "2024-25"}',
                            "expected_staging_keys": ("stg_sample",),
                            "receipt_binding": binding,
                            "result_route_ids_by_staging_key": (("stg_sample", route),),
                        }
                    ],
                    materialize=False,
                )
            assert conn.execute("SELECT count(*) FROM _staging_chunk_journal").fetchone()[0] == 0
        finally:
            conn.close()

    def test_persist_staging_uses_source_results_across_entry_list_changes(self):
        orch = Orchestrator(settings=_mock_settings())
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        frame = pl.DataFrame({"game_id": ["001"], "value": [1]})
        source_result = {
            "frames": {"stg_sample": frame},
            "source_endpoint_name": "ep1",
            "source_params_json": '{"season": "2024-25"}',
            "expected_staging_keys": ("stg_sample",),
        }

        try:
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": frame},
                run_mode="init",
                lane_id="init.season.a",
                pattern="season",
                chunk_index=0,
                chunk_params=[{"season": "2024-25"}],
                entries=[
                    SimpleNamespace(endpoint_name="ep1"),
                    SimpleNamespace(endpoint_name="ep2"),
                ],
                expected_staging_keys=["stg_sample"],
                source_results=[source_result],
                materialize=False,
            )
            orch._persist_staging_to_duckdb(
                db,
                {"stg_sample": frame},
                run_mode="init",
                lane_id="init.season.b",
                pattern="season",
                chunk_index=1,
                chunk_params=[{"season": "2024-25"}],
                entries=[SimpleNamespace(endpoint_name="ep1")],
                expected_staging_keys=["stg_sample"],
                source_results=[source_result],
                materialize=False,
            )
            StagingBatchStore(conn).materialize(["stg_sample"])
            rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
            journal_count = conn.execute(
                "SELECT count(*) FROM _staging_chunk_journal WHERE staging_key = 'stg_sample'"
            ).fetchone()[0]
        finally:
            conn.close()

        assert rows == [("001", 1)]
        assert journal_count == 1

    def test_persist_staging_replaces_changed_daily_source_results(self):
        orch = Orchestrator(settings=_mock_settings())
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        first = pl.DataFrame({"game_id": ["001"], "value": [1]})
        second = pl.DataFrame({"game_id": ["001"], "value": [2]})

        try:
            for frame in (first, second):
                orch._persist_staging_to_duckdb(
                    db,
                    {"stg_sample": frame},
                    run_mode="daily",
                    lane_id="daily.current",
                    pattern="season",
                    chunk_index=0,
                    chunk_params=[{"season": "2024-25"}],
                    entries=[SimpleNamespace(endpoint_name="ep1")],
                    expected_staging_keys=["stg_sample"],
                    source_results=[
                        {
                            "frames": {"stg_sample": frame},
                            "source_endpoint_name": "ep1",
                            "source_params_json": '{"season": "2024-25"}',
                            "expected_staging_keys": ("stg_sample",),
                        }
                    ],
                    materialize=True,
                )
            rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
            journal_count = conn.execute(
                "SELECT count(*) FROM _staging_chunk_journal WHERE staging_key = 'stg_sample'"
            ).fetchone()[0]
        finally:
            conn.close()

        assert rows == [("001", 2)]
        assert journal_count == 1

    def test_persist_staging_replaces_changed_force_backfill_source_results(self):
        orch = Orchestrator(settings=_mock_settings())
        conn = duckdb.connect(":memory:")
        db = SimpleNamespace(duckdb=conn)
        first = pl.DataFrame({"game_id": ["001"], "value": [1]})
        second = pl.DataFrame({"game_id": ["001"], "value": [2]})

        try:
            for frame in (first, second):
                orch._persist_staging_to_duckdb(
                    db,
                    {"stg_sample": frame},
                    run_mode="backfill",
                    lane_id="backfill.season",
                    pattern="season",
                    chunk_index=0,
                    chunk_params=[{"season": "2024-25"}],
                    entries=[SimpleNamespace(endpoint_name="ep1")],
                    expected_staging_keys=["stg_sample"],
                    source_results=[
                        {
                            "frames": {"stg_sample": frame},
                            "source_endpoint_name": "ep1",
                            "source_params_json": '{"season": "2024-25"}',
                            "expected_staging_keys": ("stg_sample",),
                        }
                    ],
                    replace_existing_chunks=True,
                    materialize=True,
                )
            rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
            journal_count = conn.execute(
                "SELECT count(*) FROM _staging_chunk_journal WHERE staging_key = 'stg_sample'"
            ).fetchone()[0]
        finally:
            conn.close()

        assert rows == [("001", 2)]
        assert journal_count == 1


# ---------------------------------------------------------------------------
# run_backfill tests
# ---------------------------------------------------------------------------


class TestRunBackfill:
    def test_dependent_cume_scope_auto_includes_its_foundation(self):
        item = _cume_player_plan_item()

        filtered = _filter_backfill_plan(
            [item],
            endpoints=["cume_stats_player"],
            patterns=None,
        )

        assert filtered == [item]
        assert [entry.endpoint_name for entry in filtered[0].entries] == ["cume_stats_player_games"]
        assert [entry.endpoint_name for entry in filtered[0].coverage_entries] == [
            "cume_stats_player_games",
            "cume_stats_player",
        ]

    def test_foundation_only_cume_scope_does_not_add_its_dependent(self):
        filtered = _filter_backfill_plan(
            [_cume_player_plan_item()],
            endpoints=["cume_stats_player_games"],
            patterns=None,
        )

        assert len(filtered) == 1
        assert filtered[0].cume_dependency is None
        assert [entry.endpoint_name for entry in filtered[0].entries] == ["cume_stats_player_games"]

    def test_requested_endpoint_must_have_a_concrete_route(self):
        with pytest.raises(ExtractionError, match="player_vs_player"):
            _require_requested_endpoint_routes({"player_vs_player"})

    def test_discovery_backed_endpoint_satisfies_the_plan_contract(self):
        _require_requested_endpoint_routes(
            {"league_game_log"},
            discovery_backed_endpoints=frozenset({"league_game_log"}),
        )

    def test_discovery_backed_endpoint_rejects_unrelated_pattern(self):
        with pytest.raises(ExtractionError, match="league_game_log.*player"):
            _require_requested_endpoint_routes(
                {"league_game_log"},
                requested_patterns={"player"},
                discovery_backed_endpoints=frozenset({"league_game_log"}),
            )

    @pytest.mark.parametrize(
        ("endpoint_name", "pattern"),
        [
            ("box_score_traditional", "game"),
            ("video_details", "player_team_season"),
        ],
    )
    def test_executable_route_accepts_typed_zero_row_workload(
        self,
        endpoint_name: str,
        pattern: str,
    ):
        _require_requested_endpoint_routes(
            {endpoint_name},
            requested_patterns={pattern},
        )

    def test_requested_endpoint_rejects_unsupported_mixed_pattern(self):
        with pytest.raises(ExtractionError, match="player_game_logs_v2.*season"):
            _require_requested_endpoint_routes(
                {"player_game_logs_v2"},
                requested_patterns={"player_season", "season"},
            )

    def test_run_backfill_fails_before_extraction_when_endpoint_plan_is_empty(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        mock_discovery = AsyncMock()
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                params=[
                    {
                        "player_id": 201566,
                        "team_id": 1610612737,
                        "season": "2024-25",
                        "season_type": "Regular Season",
                    }
                ]
            )
        )
        mock_runner = _mock_runner()

        with (
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch("nbadb.orchestrate.orchestrator.build_extraction_plan", return_value=[]),
            pytest.raises(ExtractionError, match="player_vs_player"),
        ):
            asyncio.run(
                orch.run_backfill(
                    seasons=["2024-25"],
                    endpoints=["player_vs_player"],
                    extract_only=True,
                    season_types=["Regular Season"],
                )
            )

        mock_runner.run_pattern_result.assert_not_called()

    def test_run_backfill_endpoint_scope_skips_unneeded_game_discovery(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = ([], pl.DataFrame())
        mock_discovery.discover_all_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params.return_value = []
        mock_discovery.discover_current_team_ids.return_value = []

        mock_runner = _mock_runner()

        with (
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
        ):
            asyncio.run(
                orch.run_backfill(
                    seasons=["2024-25"],
                    endpoints=["draft_combine_drill_results"],
                    extract_only=True,
                )
            )

        mock_discovery.discover_game_ids.assert_not_called()
        mock_discovery.discover_all_player_ids.assert_not_called()
        mock_discovery.discover_team_ids.assert_not_called()
        mock_discovery.discover_game_dates.assert_not_called()
        mock_discovery.discover_current_team_ids.assert_not_called()
        mock_discovery.discover_player_team_season_params.assert_not_called()
        mock_runner.run_pattern_result.assert_awaited_once()
        assert mock_runner.run_pattern_result.await_args.args[0] == "season"

    def test_run_backfill_scopes_discovery_to_requested_patterns(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_all_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2024-10-22"]}),
        )
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                params=[
                    {
                        "player_id": 201566,
                        "team_id": 1610612737,
                        "season": "2024-25",
                        "season_type": "Regular Season",
                    }
                ]
            )
        )

        mock_runner = _mock_runner()

        with (
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch("nbadb.orchestrate.orchestrator.build_extraction_plan", return_value=[]),
        ):
            result = asyncio.run(
                orch.run_backfill(
                    seasons=["2024-25"],
                    patterns=["player", "team", "static"],
                    extract_only=True,
                )
            )

        assert isinstance(result, PipelineResult)
        mock_discovery.discover_all_player_ids.assert_awaited_once()
        mock_discovery.discover_team_ids.assert_awaited_once()
        mock_discovery.discover_game_ids_result.assert_not_called()
        mock_discovery.discover_game_dates.assert_not_called()
        mock_discovery.discover_player_team_season_params_result.assert_not_called()

    def test_run_backfill_requires_complete_player_discovery_for_player_season_scope(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_all_player_ids.return_value = []
        mock_runner = _mock_runner()

        with (
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            pytest.raises(InitDiscoveryCoverageError, match="player discovery returned no ids"),
        ):
            asyncio.run(
                orch.run_backfill(
                    seasons=["1946-47"],
                    endpoints=["player_dash_last_n_games"],
                    patterns=["player_season"],
                    extract_only=True,
                )
            )

        mock_discovery.discover_all_player_ids.assert_awaited_once_with(season="1946-47")
        mock_runner.run_pattern_result.assert_not_called()


# ---------------------------------------------------------------------------
# run_daily tests
# ---------------------------------------------------------------------------


class TestRunDaily:
    def test_run_daily_uses_public_recurring_path_without_successor_candidate(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()

        with patch.object(
            orch,
            "_run_daily",
            AsyncMock(return_value=PipelineResult(tables_updated=1)),
        ) as run:
            result = asyncio.run(orch.run_daily())

        run.assert_awaited_once_with()
        assert result.tables_updated == 1

    def test_run_daily_returns_pipeline_result(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        phase_order: list[str] = []

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=_ALL_SEASON_TYPES,
            )
        )

        mock_runner = _mock_runner()

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_persist_staging_to_duckdb"),
            patch.object(orch, "_materialize_staging_batches"),
            patch.object(
                orch,
                "_load_staging_from_duckdb",
                return_value={"stg_daily": game_log_df},
            ),
            patch.object(
                orch,
                "_transform_and_load",
                return_value=(1, 50, 0),
            ) as mock_transform,
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                return_value=_mock_live_extraction(),
            ) as mock_live,
        ):
            mock_live.side_effect = lambda *_args, **_kwargs: (
                phase_order.append("live-persist") or _mock_live_extraction()
            )
            mock_transform.side_effect = lambda *_args, **_kwargs: (
                phase_order.append("strict-transform") or (1, 50, 0)
            )
            result = asyncio.run(orch._run_daily())

        assert isinstance(result, PipelineResult)
        assert result.tables_updated == 1
        assert mock_transform.call_args.kwargs == {
            "mode": "replace",
            "require_complete_transforms": True,
            "materialize_empty_outputs": True,
            "include_live_transforms": True,
        }
        mock_live.assert_called_once_with(db, run_mode="daily")
        assert phase_order == ["live-persist", "strict-transform"]

    def test_run_daily_uses_full_season_type_universe(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=_ALL_SEASON_TYPES,
            )
        )

        mock_runner = _mock_runner(skipped=0)
        mock_extract = AsyncMock(return_value=ExtractionOutcome(raw={}))
        expected_season_types = list(_ALL_SEASON_TYPES)

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(
                orch,
                "_discover_current_team_ids",
                AsyncMock(return_value=[1610612737]),
            ) as mock_current_teams,
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(
                orch,
                "_transform_and_load",
                return_value=(1, 50, 0),
            ) as mock_transform,
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                return_value=_mock_live_extraction(
                    game_ids=("0022400001",),
                    provider_call_count=4,
                ),
            ),
        ):
            result = asyncio.run(orch._run_daily())

        assert mock_discovery.discover_game_ids_result.await_args.kwargs["season_types"] == (
            expected_season_types
        )
        mock_current_teams.assert_awaited_once_with(
            mock_discovery,
            seasons=["2025-26"],
            refresh=True,
        )
        assert mock_extract.await_args.kwargs["season_types"] == expected_season_types
        assert mock_transform.call_args.kwargs == {
            "mode": "replace",
            "require_complete_transforms": True,
            "materialize_empty_outputs": True,
            "include_live_transforms": True,
        }
        assert result.tables_updated == 1
        assert result.rows_total == 50

    def test_run_daily_fails_before_extraction_when_game_discovery_is_incomplete(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
            covered_combos=frozenset({("2025-26", "Regular Season")}),
        )
        mock_runner = _mock_runner()
        mock_extract = AsyncMock()

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            pytest.raises(InitDiscoveryCoverageError, match="incomplete game discovery"),
        ):
            asyncio.run(orch._run_daily())

        mock_extract.assert_not_awaited()
        mock_discovery.discover_player_ids.assert_not_awaited()
        mock_discovery.discover_player_team_season_params_result.assert_not_awaited()

    def test_run_daily_disables_static_in_shared_helper(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=_ALL_SEASON_TYPES,
            )
        )

        mock_runner = _mock_runner(skipped=0)
        mock_extract = AsyncMock(return_value=ExtractionOutcome(raw={}))

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)),
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                return_value=_mock_live_extraction(),
            ),
        ):
            asyncio.run(orch._run_daily())

        assert mock_extract.await_args.kwargs["include_static"] is False

    def test_run_daily_loads_persisted_staging_when_extraction_is_empty(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.has_done_entries.return_value = True

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=_ALL_SEASON_TYPES,
            )
        )

        recovered_raw = {
            "stg_league_game_log": pl.DataFrame(
                {"game_id": ["0022400001"], "game_date": ["2026-02-28"]}
            )
        }
        mock_runner = _mock_runner(planned_calls=1, skipped=1, skipped_due_to_journal=1)
        mock_extract = AsyncMock(return_value=ExtractionOutcome(raw={}))

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(
                orch, "_load_staging_from_duckdb", return_value=recovered_raw
            ) as mock_load,
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)) as mock_transform,
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                return_value=_mock_live_extraction(),
            ),
        ):
            result = asyncio.run(orch._run_daily())

        mock_load.assert_called_once_with(db)
        assert mock_transform.call_args.args[1] is recovered_raw
        assert result.tables_updated == 1

    def test_run_daily_stops_before_phase_b_after_current_run_failure(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.has_done_entries.return_value = True

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=_ALL_SEASON_TYPES,
            )
        )

        mock_runner = _mock_runner(
            planned_calls=1,
            skipped=0,
            skipped_due_to_journal=0,
            failed_current_run=1,
        )
        mock_extract = AsyncMock(
            return_value=ExtractionOutcome(
                raw={"stg_league_game_log": game_log_df},
                failed_calls=1,
                errors=['league_game_log[{"season":"2025-26"}]: TimeoutError'],
            )
        )

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(
                orch,
                "_load_staging_from_duckdb",
                return_value={"stg_league_game_log": game_log_df},
            ) as mock_load,
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)) as mock_transform,
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                return_value=_mock_live_extraction(),
            ) as mock_live,
        ):
            result = asyncio.run(orch._run_daily())

        mock_load.assert_not_called()
        mock_transform.assert_not_called()
        mock_live.assert_not_called()
        assert result.failed_extractions == 1
        assert result.errors == ['league_game_log[{"season":"2025-26"}]: TimeoutError']

    def test_run_daily_live_snapshot_failures_raise(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=_ALL_SEASON_TYPES,
            )
        )

        mock_runner = _mock_runner(skipped=0)

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_persist_staging_to_duckdb"),
            patch.object(orch, "_materialize_staging_batches"),
            patch.object(
                orch,
                "_load_staging_from_duckdb",
                return_value={"stg_daily": game_log_df},
            ),
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)),
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                side_effect=RuntimeError("boom"),
            ),
        ):
            try:
                asyncio.run(orch._run_daily())
            except RuntimeError as exc:
                assert str(exc) == "boom"
            else:
                raise AssertionError("run_daily should propagate live snapshot failures")


# ---------------------------------------------------------------------------
# run_retry tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# run_monthly tests
# ---------------------------------------------------------------------------


class TestRunMonthly:
    def test_run_monthly_uses_public_recurring_path_without_successor_candidate(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()

        with patch.object(
            orch,
            "_run_monthly",
            AsyncMock(return_value=PipelineResult(tables_updated=1)),
        ) as run:
            result = asyncio.run(orch.run_monthly())

        run.assert_awaited_once_with()
        assert result.tables_updated == 1

    def test_run_monthly_returns_pipeline_result(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2023-24", "2024-25", "2025-26"),
            season_types=_ALL_SEASON_TYPES,
        )
        monthly_players = {
            "2023-24": [1, 2],
            "2024-25": [2, 3],
            "2025-26": [3, 4],
        }
        mock_discovery.discover_all_player_ids_result.side_effect = lambda *, season: (
            _player_id_discovery_result(
                season,
                ids=monthly_players[season],
            )
        )
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2026-02-28"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2023-24", "2024-25", "2025-26"),
                season_types=_ALL_SEASON_TYPES,
            )
        )

        mock_runner = _mock_runner(skipped=0)

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_RECENT_SEASONS, return_value=["2023-24", "2024-25", "2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(
                orch,
                "_discover_current_team_ids",
                AsyncMock(return_value=[1610612737]),
            ) as mock_current_teams,
            patch.object(orch, "_persist_staging_to_duckdb"),
            patch.object(orch, "_materialize_staging_batches"),
            patch.object(
                orch,
                "_load_staging_from_duckdb",
                return_value={"stg_monthly": game_log_df},
            ),
            patch.object(
                orch,
                "_transform_and_load",
                return_value=(1, 50, 0),
            ) as mock_transform,
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                return_value=_mock_live_extraction(),
            ) as mock_live,
        ):
            result = asyncio.run(orch._run_monthly())

        assert isinstance(result, PipelineResult)
        assert result.tables_updated == 1
        assert mock_transform.call_args.kwargs == {
            "mode": "replace",
            "require_complete_transforms": True,
            "materialize_empty_outputs": True,
            "include_live_transforms": True,
        }
        assert mock_discovery.discover_game_ids_result.await_args.kwargs["season_types"] == list(
            _ALL_SEASON_TYPES
        )
        mock_current_teams.assert_awaited_once_with(
            mock_discovery,
            seasons=["2023-24", "2024-25", "2025-26"],
            refresh=True,
        )
        assert [
            call.kwargs["season"]
            for call in mock_discovery.discover_all_player_ids_result.await_args_list
        ] == ["2023-24", "2024-25", "2025-26"]
        mock_discovery.discover_player_ids.assert_not_awaited()
        mock_live.assert_called_once_with(db, run_mode="monthly")

    def test_run_monthly_fails_before_extraction_when_game_discovery_is_incomplete(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
            covered_combos=frozenset({("2025-26", "Regular Season")}),
        )
        mock_discovery.discover_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_runner = _mock_runner()
        mock_extract = AsyncMock()

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_RECENT_SEASONS, return_value=["2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            pytest.raises(InitDiscoveryCoverageError, match="incomplete game discovery"),
        ):
            asyncio.run(orch._run_monthly())

        mock_extract.assert_not_awaited()
        mock_discovery.discover_current_team_ids.assert_not_awaited()
        mock_discovery.discover_player_team_season_params_result.assert_not_awaited()

    def test_run_monthly_fails_before_extraction_when_any_player_season_is_incomplete(self):
        orch, _db, _journal = _build_orchestrator_with_mocks()
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            seasons=("2024-25", "2025-26"),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_all_player_ids_result.side_effect = [
            _player_id_discovery_result("2024-25", ids=[1]),
            PlayerIdDiscoveryResult(
                ids=[],
                requested_season="2025-26",
                source="common_all_players",
                failure_kind="response",
            ),
        ]
        mock_runner = _mock_runner()
        mock_extract = AsyncMock()

        with (
            patch(_RECENT_SEASONS, return_value=["2024-25", "2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            pytest.raises(
                InitDiscoveryCoverageError,
                match="historical player discovery incomplete for 2025-26: response",
            ),
        ):
            asyncio.run(orch._run_monthly())

        mock_extract.assert_not_awaited()
        mock_discovery.discover_player_ids.assert_not_awaited()
        mock_discovery.discover_current_team_ids.assert_not_awaited()
        mock_discovery.discover_player_team_season_params_result.assert_not_awaited()

    def test_run_monthly_sets_duration(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_all_player_ids_result.return_value = _player_id_discovery_result(
            "2025-26"
        )
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=_ALL_SEASON_TYPES,
            )
        )

        mock_runner = _mock_runner(skipped=0)

        with (
            patch(_RECENT_SEASONS, return_value=["2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(0, 0, 0)),
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                return_value=_mock_live_extraction(),
            ),
        ):
            result = asyncio.run(orch._run_monthly())

        assert isinstance(result, PipelineResult)
        assert result.duration_seconds >= 0

    def test_run_monthly_loads_persisted_staging_when_extraction_is_empty(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.has_done_entries.return_value = True

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_all_player_ids_result.return_value = _player_id_discovery_result(
            "2025-26"
        )
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = ["2026-02-28"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=_ALL_SEASON_TYPES,
            )
        )

        recovered_raw = {
            "stg_league_game_log": pl.DataFrame(
                {"game_id": ["0022400001"], "game_date": ["2026-02-28"]}
            )
        }
        mock_runner = _mock_runner(planned_calls=1, skipped=1, skipped_due_to_journal=1)
        mock_extract = AsyncMock(
            return_value=ExtractionOutcome(raw={"stg_league_game_log": game_log_df})
        )

        with (
            patch(_RECENT_SEASONS, return_value=["2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(
                orch, "_load_staging_from_duckdb", return_value=recovered_raw
            ) as mock_load,
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)) as mock_transform,
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                return_value=_mock_live_extraction(),
            ),
        ):
            result = asyncio.run(orch._run_monthly())

        mock_load.assert_called_once_with(db)
        assert mock_transform.call_args.args[1] is recovered_raw
        assert result.tables_updated == 1

    def test_run_monthly_stops_before_phase_b_after_current_run_failure(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.has_done_entries.return_value = True

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2025-26",),
            season_types=_ALL_SEASON_TYPES,
        )
        mock_discovery.discover_all_player_ids_result.return_value = _player_id_discovery_result(
            "2025-26"
        )
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = ["2026-02-28"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=_ALL_SEASON_TYPES,
            )
        )
        mock_runner = _mock_runner(
            planned_calls=1,
            skipped=0,
            skipped_due_to_journal=0,
            failed_current_run=1,
        )
        mock_extract = AsyncMock(
            return_value=ExtractionOutcome(
                raw={"stg_league_game_log": game_log_df},
                failed_calls=1,
                errors=['league_game_log[{"season":"2025-26"}]: TimeoutError'],
            )
        )

        with (
            patch(_RECENT_SEASONS, return_value=["2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(
                orch, "_load_staging_from_duckdb", return_value={"stg_league_game_log": game_log_df}
            ) as mock_load,
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)) as mock_transform,
            patch.object(
                orch,
                "_persist_recurring_live_snapshot",
                return_value=_mock_live_extraction(),
            ) as mock_live,
        ):
            result = asyncio.run(orch._run_monthly())

        mock_load.assert_not_called()
        mock_transform.assert_not_called()
        mock_live.assert_not_called()
        assert result.failed_extractions == 1
        assert result.errors == ['league_game_log[{"season":"2025-26"}]: TimeoutError']


# ---------------------------------------------------------------------------
# run_retry tests
# ---------------------------------------------------------------------------


class TestRunFull:
    def test_skips_malformed_failed_params_json(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.get_failed.side_effect = [
            [
                ("league_game_log", '{"season": "2024-25"}', "TimeoutError"),
                ("league_game_log", '{"season":', "JSONDecodeError"),
            ],
            [],
        ]

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result()
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(season_types=_ALL_SEASON_TYPES)
        )

        mock_runner = _mock_runner(skipped=0)

        with (
            patch(_SEASON_RANGE, return_value=[]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_GET_BY_PATTERN, return_value=[]),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(0, 0, 0)),
        ):
            result = asyncio.run(orch.run_retry())

        assert isinstance(result, PipelineResult)
        assert result.failed_extractions == 0
        assert journal.get_failed.call_args_list[0].kwargs == {
            "include_exhausted": True,
            "include_abandoned": True,
        }
        mock_runner.run_pattern_result.assert_awaited_once()
        assert mock_runner.run_pattern_result.await_args.args[0] == "season"
        assert mock_runner.run_pattern_result.await_args.args[1] == [{"season": "2024-25"}]

    def test_run_retry_loads_persisted_staging_when_extraction_is_empty(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.has_done_entries.return_value = True

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
        )
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = ["2026-02-28"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(season_types=_ALL_SEASON_TYPES)
        )

        recovered_raw = {
            "stg_league_game_log": pl.DataFrame(
                {"game_id": ["0022400001"], "game_date": ["2026-02-28"]}
            )
        }
        mock_runner = _mock_runner(planned_calls=1, skipped=1, skipped_due_to_journal=1)
        mock_extract = AsyncMock(return_value=ExtractionOutcome(raw={}))

        with (
            patch(_SEASON_RANGE, return_value=[]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(
                orch, "_load_staging_from_duckdb", return_value=recovered_raw
            ) as mock_load,
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)) as mock_transform,
        ):
            result = asyncio.run(orch.run_retry())

        mock_load.assert_called_once_with(db)
        assert mock_transform.call_args.args[1] is recovered_raw
        assert result.tables_updated == 1

    def test_retries_failed_extractions(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        # First call returns failures, second call (after retry) returns empty
        journal.get_failed.side_effect = [
            [("league_game_log", '{"season": "2024-25"}', "TimeoutError")],
            [],
        ]

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result()
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(season_types=_ALL_SEASON_TYPES)
        )

        mock_runner = _mock_runner()
        mock_extract = AsyncMock(return_value=ExtractionOutcome(raw={}))

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(orch, "_transform_and_load", return_value=(0, 0, 0)),
        ):
            result = asyncio.run(orch.run_retry())

        assert isinstance(result, PipelineResult)
        assert result.failed_extractions == 0
        assert journal.get_failed.call_args_list[0].kwargs == {
            "include_exhausted": True,
            "include_abandoned": True,
        }
        assert journal.get_failed.call_args_list[1].kwargs == {
            "include_exhausted": True,
            "include_abandoned": True,
        }
        assert mock_extract.await_args.kwargs["skip_items"] == {
            ("league_game_log", '{"season": "2024-25"}'),
        }

    def test_run_retry_does_not_skip_failed_direct_retry_items(self):
        orch, _db, journal = _build_orchestrator_with_mocks()
        journal.get_failed.side_effect = [
            [("league_game_log", '{"season": "2024-25"}', "TimeoutError")],
            [("league_game_log", '{"season": "2024-25"}', "TimeoutError")],
        ]

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result()
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(season_types=_ALL_SEASON_TYPES)
        )

        mock_runner = _mock_runner(
            run_pattern_result=AsyncMock(
                return_value=PatternExtractionResult(
                    frames={},
                    eligible_calls=1,
                    failure_count=1,
                    errors=['league_game_log[{"season":"2024-25"}]: TimeoutError'],
                )
            )
        )
        mock_extract = AsyncMock(return_value=ExtractionOutcome(raw={}))

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(orch, "_transform_and_load", return_value=(0, 0, 0)),
        ):
            result = asyncio.run(orch.run_retry())

        assert isinstance(result, PipelineResult)
        assert result.failed_extractions == 1
        assert mock_extract.await_args.kwargs["skip_items"] == set()
