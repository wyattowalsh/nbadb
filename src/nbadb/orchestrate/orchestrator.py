from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, cast

import duckdb
from loguru import logger

from nbadb.core.config import NbaDbSettings, get_settings
from nbadb.core.db import DBManager
from nbadb.core.errors import ExtractionError
from nbadb.core.types import SeasonType
from nbadb.extract.registry import registry as _global_registry
from nbadb.load.multi import create_multi_loader
from nbadb.orchestrate.discovery import (
    EntityDiscovery,
    GameDiscoveryResult,
    PlayerTeamSeasonDiscoveryResult,
)
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope, DiscoveryArtifactStore
from nbadb.orchestrate.execution_policy import endpoint_family
from nbadb.orchestrate.extraction_contract import (
    DISCOVERY_SEED_ENDPOINT_PATTERNS,
    DISCOVERY_SEED_OWNED_ENDPOINTS,
)
from nbadb.orchestrate.extraction_progress import ExtractionProgressStore
from nbadb.orchestrate.extractor_runner import ExtractorRunner, PatternExtractionResult
from nbadb.orchestrate.init_coverage import InitDiscoveryCoverageError
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.live_snapshot import LiveSnapshotWarehouse
from nbadb.orchestrate.planning import (
    ExtractionPlanItem,
    build_extraction_plan,
    executable_endpoint_routes,
    resolve_video_context_measures,
)
from nbadb.orchestrate.seasons import (
    current_season,
    recent_seasons,
    season_range,
)
from nbadb.orchestrate.staging_batches import (
    StagingBatchStore,
    StagingChunkMetadata,
    StagingFrameBatch,
    digest_jsonable,
    frame_content_hash,
)
from nbadb.orchestrate.staging_map import STAGING_MAP
from nbadb.orchestrate.transformers import (
    discover_all_transformers,
    require_complete_transformer_universe,
)
from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore
from nbadb.transform.pipeline import TransformPipeline
from nbadb.transform.quality import DataQualityMonitor
from nbadb.transform.schema_version import schema_hash_for_frame

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from concurrent.futures import ThreadPoolExecutor

    import polars as pl


DEFAULT_SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)
type LoadMode = Literal["replace", "append"]


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
    ) -> None:
        self._settings: NbaDbSettings = settings if settings is not None else get_settings()
        self._db: DBManager | None = None
        self._journal: PipelineJournal | None = None
        self._progress: _ProgressReporter | None = progress

    # ── lifecycle helpers ──────────────────────────────────────

    def _init_db(self) -> tuple[DBManager, PipelineJournal]:
        """Ensure DB + journal are ready, re-using if already init'd.

        Completed entries are preserved so resume stays idempotent, while any
        lingering in-progress rows from a prior process are made replayable.
        This recovery assumes a single active writer per pipeline DB/journal.
        """
        if self._db is not None and self._journal is not None:
            return self._db, self._journal

        db = DBManager(
            sqlite_path=self._settings.sqlite_path,
            duckdb_path=self._settings.duckdb_path,
        )
        db.init()
        journal = PipelineJournal(db.duckdb)
        journal.recover_interrupted_running()

        self._db = db
        self._journal = journal
        return db, journal

    def _build_runner(self, journal: PipelineJournal) -> ExtractorRunner:
        _global_registry.discover()
        return ExtractorRunner(
            registry=_global_registry,
            settings=self._settings,
            journal=journal,
            rate_limit=self._settings.rate_limit,
            progress=self._progress,
        )

    def _build_discovery(self, thread_pool: ThreadPoolExecutor | None = None) -> EntityDiscovery:
        """Create an EntityDiscovery wired to the global registry."""
        return EntityDiscovery(
            _global_registry,
            thread_pool=thread_pool,
            settings=self._settings,
        )

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
        covered_pairs: set[tuple[str, str]] | None = None,
    ) -> list[dict[str, int | str]]:
        store = self._player_team_season_workloads()
        store.upsert(
            params,
            seasons=seasons,
            season_types=season_types,
            covered_pairs=covered_pairs,
        )
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

        return PlayerTeamSeasonDiscoveryResult(
            params=[merged_params[key] for key in sorted(merged_params)],
            requested_pairs=requested_pairs,
            covered_pairs=frozenset(covered_pairs),
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

    def _run_live_snapshot_upkeep(self, *, run_mode: str) -> tuple[int, int]:
        snapshot = LiveSnapshotWarehouse(settings=self._settings).run()
        if not snapshot.game_ids:
            logger.bind(run_mode=run_mode).info("live snapshot upkeep: no active games")
            return 0, 0
        logger.bind(run_mode=run_mode).info(
            "live snapshot upkeep: {} active games, {} star tables, {} rows",
            len(snapshot.game_ids),
            snapshot.star_tables_loaded,
            snapshot.star_rows_loaded,
        )
        return snapshot.star_tables_loaded, snapshot.star_rows_loaded

    def _transform_and_load(
        self,
        db: DBManager,
        raw: dict[str, pl.DataFrame],
        journal: PipelineJournal,
        mode: LoadMode = "replace",
    ) -> tuple[int, int, int]:
        """Run transform pipeline then load all outputs.

        Returns (tables_updated, rows_total, failed_loads).
        The transform pipeline connection is always cleaned up via
        try/finally to prevent DuckDB connection leaks (QUAL-010).
        """
        pp = self._progress

        # Build staging dict (LazyFrames)
        staging: dict[str, pl.LazyFrame] = {key: df.lazy() for key, df in raw.items()}

        # Transform
        transformers = discover_all_transformers(include_live=False)
        require_complete_transformer_universe(transformers, include_live=False)
        pipeline = TransformPipeline(db.duckdb)
        pipeline.register_all(transformers)
        n_transformers = len(transformers)
        if pp is not None:
            pp.start_pattern(f"Transform ({n_transformers})", total=n_transformers)
        try:
            outputs = pipeline.run(
                staging,
                validate_input_schemas=True,
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
        non_empty = {t: df for t, df in outputs.items() if not df.is_empty()}
        if pp is not None:
            pp.start_pattern(f"Load ({len(non_empty)})", total=len(non_empty))

        for table, df in outputs.items():
            if df.is_empty():
                logger.debug("skip load (empty): {}", table)
                continue
            try:
                loader.load(table, df, mode=mode)
                rows = df.shape[0]
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
                journal.set_watermark(table, "last_load", current_season(), rows)
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

        return tables_updated, rows_total, failed_loads

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
        entries: list[object] | None = None,
        expected_staging_keys: list[str] | None = None,
        source_results: list[dict[str, object]] | None = None,
        dedupe_materialized: bool | None = None,
        replace_existing_chunks: bool = False,
        materialize: bool = True,
    ) -> None:
        """Persist in-memory staging DataFrames to DuckDB tables.

        Ensures staging data survives process crashes between extraction
        and transform phases without dropping prior persisted rows from
        earlier iterations or resumed shards.
        """
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
        store = StagingBatchStore(db.duckdb)
        if source_results:
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
                    )
                )
            result = store.persist_frame_batches(source_batches, materialize=materialize)
        else:
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
        logger.info(
            "persisted {} staging chunk tables to DuckDB ({} rows)",
            result.staging_tables,
            result.rows_persisted,
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
        return StagingBatchStore(db.duckdb).materialize(keys)

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

    def close(self) -> None:
        """Close DB connections. Safe to call multiple times."""
        if self._db is not None:
            self._db.close()
            self._db = None
            self._journal = None

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
                None if refresh_current_scope else artifacts.load_game_log_frame(game_scope)
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
            cached_player_ids = [] if refresh_current_scope else artifacts.load_ids(player_scope)
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
            cached_team_ids = artifacts.load_ids(team_scope)
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
        persist_results: Callable[..., None] | None = None,
        retain_in_memory: bool = True,
    ) -> ExtractionOutcome:
        """Run all extraction patterns concurrently and return combined
        raw staging data.

        Pattern groups are independent (no cross-pattern dependencies),
        so they are dispatched via ``asyncio.gather`` (INFRA-010).
        """
        pp = self._progress

        raw: dict[str, pl.DataFrame] = {}
        if not game_log_df.is_empty():
            raw["stg_league_game_log"] = game_log_df
            if persist_results is not None:
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

            def _persist_with_lane_metadata(
                frames: dict[str, pl.DataFrame],
                **metadata: object,
            ) -> None:
                if chunk_persist_results is None:
                    return
                raw_chunk_index = metadata.get("chunk_index")
                chunk_index = raw_chunk_index if isinstance(raw_chunk_index, int) else 0
                persist_metadata: dict[str, object] = {
                    "run_mode": run_mode or "unknown",
                    "lane_id": lane_id,
                    "pattern": pattern,
                    "chunk_index": chunk_index,
                    "chunk_params": cast("list[dict] | None", metadata.get("chunk_params")),
                    "entries": entries,
                    "expected_staging_keys": cast(
                        "list[str] | None",
                        metadata.get("expected_staging_keys"),
                    ),
                    "materialize": False,
                }
                source_results = cast(
                    "list[dict[str, object]] | None",
                    metadata.get("source_results"),
                )
                if source_results is not None:
                    persist_metadata["source_results"] = source_results
                chunk_persist_results(frames, **persist_metadata)

            if skip_items and chunk_persist_results is not None:
                result = await runner.run_pattern_result(
                    pattern,
                    params,
                    entries,
                    on_progress=pp,
                    skip_items=skip_items,
                    persist_chunk_results=_persist_with_lane_metadata,
                )
            elif skip_items:
                result = await runner.run_pattern_result(
                    pattern,
                    params,
                    entries,
                    on_progress=pp,
                    skip_items=skip_items,
                )
            elif chunk_persist_results is not None:
                result = await runner.run_pattern_result(
                    pattern,
                    params,
                    entries,
                    on_progress=pp,
                    persist_chunk_results=_persist_with_lane_metadata,
                )
            else:
                result = await runner.run_pattern_result(
                    pattern,
                    params,
                    entries,
                    on_progress=pp,
                )
            result_raw = result.frames

            completed_at = datetime.now(UTC)
            row_count = result.row_count
            endpoint_families = sorted(
                {
                    endpoint_family(entry.endpoint_name, getattr(entry, "param_pattern", pattern))
                    for entry in entries
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
                                        for entry in failed_item.entries
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
            discovery = self._build_discovery(thread_pool=runner._thread_pool)

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
        """Incremental update focused on recent games.

        1. Extract league_game_log for current season
        2. Filter to games within ``daily_lookback_days``
        3. Run game-level extractors for those game_ids
        4. Refresh current-season endpoints across their declared season types
        5. Transform + load (replace)
        6. Append a live snapshot when active games exist
        """
        import polars as pl

        bound_log = cast("_BoundLogger", logger.bind(run_mode="daily"))
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery(thread_pool=runner._thread_pool)

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
            extraction = await self._extract_all_patterns(
                runner,
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

            self._materialize_staging_batches(db)
            raw = self._load_staging_from_duckdb(db)
            bound_log.info("daily loaded {} staged tables from DuckDB", len(raw))

            # -- 3. Transform + Load --------------------------------
            tables_updated, rows_total, failed_loads = self._transform_and_load(
                db, raw, journal, mode="replace"
            )
            live_tables_updated, live_rows_total = self._run_live_snapshot_upkeep(run_mode="daily")
            tables_updated += live_tables_updated
            rows_total += live_rows_total

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
        """Monthly refresh of the last 3 seasons.

        Runs all pattern types for ``recent_seasons(3)`` across the full
        supported season-type universe, then appends a live snapshot when
        active games exist.
        """
        bound_log = cast("_BoundLogger", logger.bind(run_mode="monthly"))
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery(thread_pool=runner._thread_pool)

            seasons = recent_seasons(3)
            bound_log.info("monthly: seasons={}", seasons)

            # -- 1. Discover entities (parallel) --- uses shared helper
            monthly_season_types = list(DEFAULT_SEASON_TYPES)
            game_ids, player_ids, team_ids, game_dates, game_log_df = await self._discover_entities(
                discovery,
                seasons,
                bound_log,
                season_types=monthly_season_types,
                require_complete_games=True,
                refresh_mutable_entities=True,
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
                season_types=monthly_season_types,
                run_mode="monthly",
                journal=journal,
                progress_store=self._extraction_progress(),
                persist_results=lambda frames, **metadata: self._persist_staging_to_duckdb(
                    db, frames, **metadata
                ),
                retain_in_memory=False,
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

            self._materialize_staging_batches(db)
            raw = self._load_staging_from_duckdb(db)
            bound_log.info("monthly loaded {} staged tables from DuckDB", len(raw))

            # -- 3. Transform + Load --------------------------------
            tables_updated, rows_total, failed_loads = self._transform_and_load(
                db, raw, journal, mode="replace"
            )
            live_tables_updated, live_rows_total = self._run_live_snapshot_upkeep(
                run_mode="monthly"
            )
            tables_updated += live_tables_updated
            rows_total += live_rows_total

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
            discovery = self._build_discovery(thread_pool=runner._thread_pool)

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
                ) -> None:
                    source_results = cast(
                        "list[dict[str, object]] | None",
                        metadata.get("source_results"),
                    )
                    if source_results is not None:
                        self._persist_staging_to_duckdb(
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
                        return
                    self._persist_staging_to_duckdb(
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
            planner.force_reset(seasons=seasons, endpoints=endpoints, patterns=patterns)
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
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery(thread_pool=runner._thread_pool)
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

            # Filter plan items by endpoint/pattern if user requested
            if endpoints or patterns:
                ep_set = set(endpoints) if endpoints else None
                pat_set = set(patterns) if patterns else None
                filtered: list = []
                for item in plan:
                    if pat_set and item.pattern not in pat_set:
                        continue
                    if ep_set:
                        matching_entries = [e for e in item.entries if e.endpoint_name in ep_set]
                        if not matching_entries:
                            continue
                        from nbadb.orchestrate.planning import ExtractionPlanItem

                        filtered.append(
                            ExtractionPlanItem(
                                label=item.label,
                                pattern=item.pattern,
                                entries=matching_entries,
                                params=item.params,
                                priority=item.priority,
                            )
                        )
                    else:
                        filtered.append(item)
                plan = filtered

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
                if not df.is_empty():
                    raw[key] = df
                    logger.debug("loaded staging {}: {} rows", key, df.shape[0])
            except duckdb.CatalogException:
                pass  # Table doesn't exist yet
        return raw
