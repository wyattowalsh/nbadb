from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import duckdb
from loguru import logger

from nbadb.core.config import NbaDbSettings, get_settings
from nbadb.core.db import DBManager
from nbadb.core.proxy import ProxyUrlProvider, build_proxy_pool
from nbadb.extract.registry import registry as _global_registry
from nbadb.load.multi import create_multi_loader
from nbadb.orchestrate.discovery import EntityDiscovery
from nbadb.orchestrate.extractor_runner import ExtractorRunner
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.planning import build_extraction_plan
from nbadb.orchestrate.seasons import (
    current_season,
    recent_seasons,
    season_range,
)
from nbadb.orchestrate.staging_map import STAGING_MAP
from nbadb.orchestrate.transformers import (
    discover_all_transformers,
)
from nbadb.transform.pipeline import TransformPipeline

if TYPE_CHECKING:
    import polars as pl


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


class _ProgressReporter(Protocol):
    """Minimal progress surface used by the orchestrator stack."""

    def start_phase(self, name: str, total: int = 0) -> None: ...

    def update_phase_info(self, info: str) -> None: ...

    def complete_phase(self) -> None: ...

    def log_discovery(self, entity: str, count: int) -> None: ...

    def start_pattern(self, pattern: str, total: int) -> None: ...

    def advance_pattern(self, *, success: bool = True) -> None: ...

    def record_skip(self, n: int = 1) -> None: ...


class Orchestrator:
    """Main orchestration engine.

    Coordinates extraction, transformation, and loading across
    all pipeline run modes (init, daily, monthly, full).

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
        self._proxy_pool: ProxyUrlProvider | None = build_proxy_pool(self._settings)
        if self._proxy_pool is None:
            logger.debug("proxy pool: disabled")
        self._db: DBManager | None = None
        self._journal: PipelineJournal | None = None
        self._progress: _ProgressReporter | None = progress

    # ── lifecycle helpers ──────────────────────────────────────

    def _init_db(self) -> tuple[DBManager, PipelineJournal]:
        """Ensure DB + journal are ready, re-using if already init'd.

        Only resets stale *running* entries — completed entries are
        preserved so that resume works correctly (QUAL-003).
        """
        if self._db is not None and self._journal is not None:
            return self._db, self._journal

        db = DBManager(
            sqlite_path=self._settings.sqlite_path,
            duckdb_path=self._settings.duckdb_path,
        )
        db.init()
        journal = PipelineJournal(db.duckdb)
        # Only reset stale running entries — never clear completed ones
        journal.reset_stale_running()

        self._db = db
        self._journal = journal
        return db, journal

    def _build_runner(self, journal: PipelineJournal) -> ExtractorRunner:
        _global_registry.discover()
        return ExtractorRunner(
            registry=_global_registry,
            settings=self._settings,
            journal=journal,
            proxy_pool=self._proxy_pool,
            rate_limit=self._settings.rate_limit,
        )

    def _build_discovery(self) -> EntityDiscovery:
        """Create an EntityDiscovery wired to the global registry."""
        return EntityDiscovery(
            _global_registry,
            proxy_pool=self._proxy_pool,
        )

    def _build_result(
        self,
        start_time: float,
        tables: int,
        rows: int,
        failed_loads: int,
        journal: PipelineJournal,
        extra_errors: list[str] | None = None,
    ) -> PipelineResult:
        """Assemble a PipelineResult from collected counters."""
        failed = journal.get_failed()
        errors = [f"{ep}[{p}]: {err}" for ep, p, err in failed]
        if extra_errors:
            errors.extend(extra_errors)
        result = PipelineResult()
        result.tables_updated = tables
        result.rows_total = rows
        result.failed_extractions = len(failed)
        result.failed_loads = failed_loads
        result.duration_seconds = time.perf_counter() - start_time
        result.errors = errors
        return result

    def _transform_and_load(
        self,
        db: DBManager,
        raw: dict[str, pl.DataFrame],
        journal: PipelineJournal,
        mode: str = "replace",
    ) -> tuple[int, int, int]:
        """Run transform pipeline then load all outputs.

        Returns (tables_updated, rows_total, failed_loads).
        The transform pipeline connection is always cleaned up via
        try/finally to prevent DuckDB connection leaks (QUAL-010).
        """
        # Build staging dict (LazyFrames)
        staging: dict[str, pl.LazyFrame] = {key: df.lazy() for key, df in raw.items()}

        # Transform
        transformers = discover_all_transformers()
        pipeline = TransformPipeline(db.duckdb)
        pipeline.register_all(transformers)
        try:
            outputs = pipeline.run(staging, validate_input_schemas=True)
        finally:
            # TransformPipeline.run() resets _conn in its own finally,
            # but we guard here as well for safety.
            pass

        # Load
        loader = create_multi_loader(self._settings, duckdb_conn=db.duckdb)
        tables_updated = 0
        rows_total = 0
        failed_loads = 0

        for table, df in outputs.items():
            if df.is_empty():
                logger.debug("skip load (empty): {}", table)
                continue
            try:
                loader.load(table, df, mode=mode)  # type: ignore[arg-type]
                rows = df.shape[0]
                tables_updated += 1
                rows_total += rows
            except Exception as exc:
                failed_loads += 1
                logger.error("load failed for {}: {}", table, type(exc).__name__)
                continue  # skip watermark if load failed

            try:
                journal.set_watermark(table, "last_load", current_season(), rows)
            except Exception as wm_exc:
                logger.warning(
                    "watermark write failed for {}: {}",
                    table,
                    type(wm_exc).__name__,
                )

            logger.info(
                "loaded {}: {} rows ({})",
                table,
                rows,
                mode,
            )

        return tables_updated, rows_total, failed_loads

    # ── shared discovery (QUAL-006) ───────────────────────────

    async def _discover_entities(
        self,
        discovery: EntityDiscovery,
        seasons: list[str],
        bound_log: object,
        *,
        season_types: list[str] | None = None,
        include_historical_players: bool = False,
    ) -> tuple[list[str], list[int], list[int], list[str], pl.DataFrame]:
        """Discover game/player/team IDs and game dates in parallel.

        Shared by run_init, run_monthly, and any future run mode that
        needs all entity types.  Returns:
            (game_ids, player_ids, team_ids, game_dates, game_log_df)

        When *include_historical_players* is True (used by run_init),
        all players are discovered (active + retired).
        """
        import polars as pl

        pp = self._progress

        player_coro = (
            discovery.discover_all_player_ids()
            if include_historical_players
            else discovery.discover_player_ids()
        )

        results = await asyncio.gather(
            discovery.discover_game_ids(seasons, on_progress=pp, season_types=season_types),
            player_coro,
            discovery.discover_team_ids(),
            return_exceptions=True,
        )
        _game_result = results[0]
        _player_result = results[1]
        _team_result = results[2]

        if isinstance(_game_result, Exception):
            bound_log.warning("discover_game_ids failed: {}", type(_game_result).__name__)  # type: ignore[union-attr]
            game_ids: list[str] = []
            game_log_df = pl.DataFrame()
        else:
            game_ids, game_log_df = _game_result
            if pp is not None:
                pp.log_discovery("games", len(game_ids))

        if isinstance(_player_result, Exception):
            bound_log.warning("discover_player_ids failed: {}", type(_player_result).__name__)  # type: ignore[union-attr]
            player_ids: list[int] = []
        else:
            player_ids = _player_result
            if pp is not None:
                pp.log_discovery("players", len(player_ids))

        if isinstance(_team_result, Exception):
            bound_log.warning("discover_team_ids failed: {}", type(_team_result).__name__)  # type: ignore[union-attr]
            team_ids: list[int] = []
        else:
            team_ids = _team_result
            if pp is not None:
                pp.log_discovery("teams", len(team_ids))

        game_dates = await discovery.discover_game_dates(game_log_df)
        if pp is not None:
            pp.log_discovery("dates", len(game_dates))

        return game_ids, player_ids, team_ids, game_dates, game_log_df

    async def _extract_all_patterns(
        self,
        runner: ExtractorRunner,
        *,
        seasons: list[str],
        game_ids: list[str],
        player_ids: list[int],
        team_ids: list[int],
        game_dates: list[str],
        player_team_season_params: list[dict[str, int | str]] | None = None,
        game_log_df: pl.DataFrame,
        include_static: bool = True,
        season_types: list[str] | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Run all extraction patterns concurrently and return combined
        raw staging data.

        Pattern groups are independent (no cross-pattern dependencies),
        so they are dispatched via ``asyncio.gather`` (INFRA-010).
        """
        pp = self._progress

        raw: dict[str, pl.DataFrame] = {}
        if not game_log_df.is_empty():
            raw["stg_league_game_log"] = game_log_df

        plan = build_extraction_plan(
            seasons=seasons,
            game_ids=game_ids,
            player_ids=player_ids,
            team_ids=team_ids,
            game_dates=game_dates,
            player_team_season_params=player_team_season_params,
            include_static=include_static,
            season_types=season_types,
        )

        # Compute total extraction tasks for the progress bar
        total_tasks = sum(item.task_count for item in plan)
        if pp is not None:
            pp.start_phase("Extraction", total=total_tasks)

        # Run a single pattern group
        async def _run_one(
            idx: int,
            item: object,
        ) -> dict[str, pl.DataFrame]:
            label = item.label
            pattern = item.pattern
            entries = item.entries
            params = item.params
            n_tasks = item.task_count
            logger.info("Step {}/{}: {} ({} tasks)", idx, len(plan), label, n_tasks)
            if pp is not None:
                pp.start_pattern(f"{label} ({n_tasks:,})", total=n_tasks)
            return await runner.run_pattern(pattern, params, entries, on_progress=pp)

        # Group plan items by priority tier and run tiers sequentially.
        # Within each tier, patterns run concurrently.  This ensures
        # small/fast extractions complete before the massive game-level
        # extraction begins.
        tier_groups: dict[int, list[tuple[int, object]]] = {}
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
                    failed_label = tier_items[j][1].label
                    logger.error(
                        "pattern {} failed: {}",
                        failed_label,
                        type(result).__name__,
                    )
                    continue
                raw.update(result)

        if pp is not None:
            pp.complete_phase()

        return raw

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

        Only stale *running* entries are reset (via ``reset_stale_running``).
        Completed entries are never cleared, preserving progress from
        prior partial runs (QUAL-003).

        *season_types* controls which season types are extracted.
        Defaults to ``["Regular Season", "Playoffs"]``.
        """
        if season_types is None:
            season_types = ["Regular Season", "Playoffs"]

        bound_log = logger.bind(run_mode="init")
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            if journal.has_done_entries():
                bound_log.info("init resume: prior completed entries found, will skip those")

            # -- 1. Entity discovery (parallel) --------------------
            pp = self._progress
            seasons = season_range(start_season, end_season)
            discovery = self._build_discovery()

            bound_log.info(
                "init: discovering entities for {} seasons × {} season_types",
                len(seasons),
                len(season_types),
            )
            if pp is not None:
                pp.start_phase("Discovery")
                pp.update_phase_info(f"scanning {len(seasons)} seasons...")

            game_ids, player_ids, team_ids, game_dates, game_log_df = await self._discover_entities(
                discovery,
                seasons,
                bound_log,
                season_types=season_types,
                include_historical_players=True,
            )
            player_team_season_params = await discovery.discover_player_team_season_params(seasons)

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
            raw = await self._extract_all_patterns(
                runner,
                seasons=seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                game_log_df=game_log_df,
                season_types=season_types,
            )

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
        4. Refresh season-level for current season
        5. Transform + load (replace)
        """
        import polars as pl

        bound_log = logger.bind(run_mode="daily")
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery()

            season = current_season()
            bound_log.info("daily: season={}", season)

            # -- 1. Discover recent game_ids (Regular + Playoffs) -----
            _daily_st = ["Regular Season", "Playoffs"]
            game_ids, game_log_df = await discovery.discover_game_ids(
                [season], season_types=_daily_st
            )

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
            player_team_season_params = await discovery.discover_player_team_season_params([season])
            bound_log.info(
                "daily: {} active players, {} teams, {} player-team seasons for refresh",
                len(player_ids),
                len(team_ids),
                len(player_team_season_params),
            )

            # -- 3. Game + season + date + player/team extraction
            raw.update(
                await self._extract_all_patterns(
                    runner,
                    seasons=[season],
                    game_ids=game_ids,
                    player_ids=player_ids,
                    team_ids=team_ids,
                    game_dates=game_dates,
                    player_team_season_params=player_team_season_params,
                    game_log_df=pl.DataFrame(),  # already seeded above
                    include_static=False,
                    season_types=_daily_st,
                )
            )
            # Keep the seeded game_log_df (update may have cleared it)
            if not game_log_df.is_empty():
                raw.setdefault("stg_league_game_log", game_log_df)

            # -- 3. Transform + Load --------------------------------
            tables_updated, rows_total, failed_loads = self._transform_and_load(
                db, raw, journal, mode="replace"
            )

            journal.abandon_exhausted()
            result = self._build_result(
                t0,
                tables_updated,
                rows_total,
                failed_loads,
                journal=journal,
            )
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

        Runs all pattern types for ``recent_seasons(3)`` and does
        a full replace for all tables.
        """
        bound_log = logger.bind(run_mode="monthly")
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery()

            seasons = recent_seasons(3)
            bound_log.info("monthly: seasons={}", seasons)

            # -- 1. Discover entities (parallel) --- uses shared helper
            _monthly_st = ["Regular Season", "Playoffs"]
            game_ids, player_ids, team_ids, game_dates, game_log_df = await self._discover_entities(
                discovery, seasons, bound_log, season_types=_monthly_st
            )
            player_team_season_params = await discovery.discover_player_team_season_params(seasons)

            # -- 2. Extract all patterns ----------------------------
            raw = await self._extract_all_patterns(
                runner,
                seasons=seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                game_log_df=game_log_df,
                season_types=_monthly_st,
            )

            # -- 3. Transform + Load --------------------------------
            tables_updated, rows_total, failed_loads = self._transform_and_load(
                db, raw, journal, mode="replace"
            )

            journal.abandon_exhausted()
            result = self._build_result(
                t0,
                tables_updated,
                rows_total,
                failed_loads,
                journal=journal,
            )
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

    async def run_full(self) -> PipelineResult:
        """Fill gaps and retry all failed extractions.

        1. Read journal for failed/incomplete extractions
        2. Retry those extractions
        3. Check watermarks for missing seasons
        4. Transform + load
        """
        bound_log = logger.bind(run_mode="full")
        t0 = time.perf_counter()

        db, journal = self._init_db()
        async with self._build_runner(journal) as runner:
            discovery = self._build_discovery()

            # -- 1. Retry failed extractions ------------------------
            failed = journal.get_failed()
            bound_log.info(
                "full: {} failed extractions to retry",
                len(failed),
            )

            # Group failed by pattern for batched re-extraction
            failed_by_entry: dict[str, list[dict]] = {}  # endpoint -> params
            for endpoint, params_json, _error in failed:
                try:
                    params = json.loads(params_json)
                except (TypeError, json.JSONDecodeError) as exc:
                    quarantine_error = f"invalid_params_json:{type(exc).__name__}"
                    journal.record_failure(endpoint, params_json, quarantine_error)
                    bound_log.warning(
                        "full: skipping malformed failed params_json for {}: {} ({})",
                        endpoint,
                        params_json,
                        quarantine_error,
                    )
                    continue
                if not isinstance(params, dict):
                    quarantine_error = f"invalid_params_json:{type(params).__name__}"
                    journal.record_failure(endpoint, params_json, quarantine_error)
                    bound_log.warning(
                        "full: skipping non-object failed params_json for {}: {} ({})",
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
                retry_raw = await runner.run_pattern(pattern, param_list, ep_entries)
                raw.update(retry_raw)

            # -- 2. Gap-fill ALL patterns (not just season+game) ------
            _full_st = ["Regular Season", "Playoffs"]
            seasons = season_range()

            # Discover entities for gap-filling
            game_ids, player_ids, team_ids, game_dates, game_log_df = await self._discover_entities(
                discovery, seasons, bound_log, season_types=_full_st
            )
            player_team_season_params = await discovery.discover_player_team_season_params(seasons)
            if not game_log_df.is_empty():
                raw.setdefault("stg_league_game_log", game_log_df)

            # Run all patterns — runner will skip already-extracted via journal
            gap_raw = await self._extract_all_patterns(
                runner,
                seasons=seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                game_log_df=game_log_df,
                season_types=_full_st,
            )
            raw.update(gap_raw)

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
            )
            result.skipped_extractions = runner.skipped
            runner.log_latency_summary()

        bound_log.info(
            "full complete: {} tables, {} rows, {:.1f}s, {} remaining failures",
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
            Defaults to ``["Regular Season", "Playoffs"]``.
        """
        if season_types is None:
            season_types = ["Regular Season", "Playoffs"]

        bound_log = logger.bind(run_mode="backfill")
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
            discovery = self._build_discovery()
            effective_seasons = seasons if seasons is not None else season_range()

            bound_log.info(
                "backfill: {} seasons, endpoints={}, patterns={}, force={}",
                len(effective_seasons),
                endpoints,
                patterns,
                force,
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
            )
            player_team_season_params = await discovery.discover_player_team_season_params(
                effective_seasons
            )
            if pp is not None:
                pp.complete_phase()

            # -- 2. Build plan and filter by user scope ─────────────────
            plan = build_extraction_plan(
                seasons=effective_seasons,
                game_ids=game_ids,
                player_ids=player_ids,
                team_ids=team_ids,
                game_dates=game_dates,
                player_team_season_params=player_team_season_params,
                season_types=season_types,
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

            for idx, item in enumerate(plan, 1):
                bound_log.info(
                    "backfill step {}/{}: {} ({} tasks)",
                    idx,
                    len(plan),
                    item.label,
                    item.task_count,
                )
                if pp is not None:
                    pp.start_pattern(f"{item.label} ({item.task_count:,})", total=item.task_count)
                result_raw = await runner.run_pattern(
                    item.pattern, item.params, item.entries, on_progress=pp
                )
                raw.update(result_raw)

            if pp is not None:
                pp.complete_phase()

            # -- 4. Transform + Load ─────────────────────────────────────
            tables_updated = 0
            rows_total = 0
            failed_loads = 0

            if extract_only and raw:
                # Persist staging tables to DuckDB so downstream merge jobs
                # (or later --transform-only runs) can read them.
                bound_log.info("extract-only: persisting {} staging tables to DuckDB", len(raw))
                for key, df in raw.items():
                    if not df.is_empty():
                        db.duckdb.register("_staging_tmp", df)
                        db.duckdb.execute(
                            f'CREATE OR REPLACE TABLE "{key}" AS SELECT * FROM _staging_tmp'
                        )
                        db.duckdb.unregister("_staging_tmp")
                bound_log.info("extract-only: staging tables persisted")
            elif raw:
                if pp is not None:
                    pp.start_phase("Transform & Load")
                    pp.update_phase_info(f"{len(raw)} staging tables")
                tables_updated, rows_total, failed_loads = self._transform_and_load(
                    db, raw, journal, mode="replace"
                )
                if pp is not None:
                    pp.complete_phase()

            # -- 5. Result ───────────────────────────────────────────────
            journal.abandon_exhausted()
            result = self._build_result(
                t0, tables_updated, rows_total, failed_loads, journal=journal
            )
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

        raw: dict[str, pl.DataFrame] = {}
        for key in keys:
            try:
                df = db.duckdb.execute(f"SELECT * FROM {key}").pl()
                if not df.is_empty():
                    raw[key] = df
                    logger.debug("loaded staging {}: {} rows", key, df.shape[0])
            except duckdb.CatalogException:
                pass  # Table doesn't exist yet
        return raw
