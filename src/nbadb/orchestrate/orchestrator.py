from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from nbadb.core.config import NbaDbSettings, get_settings
from nbadb.core.db import DBManager
from nbadb.core.proxy import build_proxy_pool
from nbadb.extract.registry import registry as _global_registry
from nbadb.load.multi import create_multi_loader
from nbadb.orchestrate.discovery import EntityDiscovery
from nbadb.orchestrate.extractor_runner import ExtractorRunner
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.seasons import (
    current_season,
    recent_seasons,
    season_range,
)
from nbadb.orchestrate.staging_map import (
    STAGING_MAP,
    get_by_pattern,
)
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


class Orchestrator:
    """Main orchestration engine.

    Coordinates extraction, transformation, and loading across
    all pipeline run modes (init, daily, monthly, full).

    Resume logic is handled automatically via the extraction
    journal -- each call checks ``journal.was_extracted()``
    before invoking an endpoint.
    """

    def __init__(self, settings: NbaDbSettings | None = None) -> None:
        self._settings = settings or get_settings()
        self._proxy_pool = build_proxy_pool(self._settings)
        if self._proxy_pool is None:
            logger.debug("proxy pool: disabled")
        self._db: DBManager | None = None
        self._journal: PipelineJournal | None = None

    # ── lifecycle helpers ──────────────────────────────────────

    def _init_db(self) -> tuple[DBManager, PipelineJournal]:
        """Ensure DB + journal are ready, re-using if already init'd."""
        if self._db is not None and self._journal is not None:
            return self._db, self._journal

        db = DBManager(
            sqlite_path=self._settings.sqlite_path,
            duckdb_path=self._settings.duckdb_path,
        )
        db.init()
        journal = PipelineJournal(db.duckdb)
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
        )

    def _build_discovery(self) -> EntityDiscovery:
        """Create an EntityDiscovery wired to the global registry."""
        return EntityDiscovery(_global_registry, proxy_pool=self._proxy_pool)

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
        """
        # Build staging dict (LazyFrames)
        staging: dict[str, pl.LazyFrame] = {key: df.lazy() for key, df in raw.items()}

        # Transform
        transformers = discover_all_transformers()
        pipeline = TransformPipeline(db.duckdb)
        pipeline.register_all(transformers)
        outputs = pipeline.run(staging)

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

    async def _extract_all_patterns(
        self,
        runner: ExtractorRunner,
        *,
        seasons: list[str],
        game_ids: list[str],
        player_ids: list[int],
        team_ids: list[int],
        game_dates: list[str],
        game_log_df: pl.DataFrame,
    ) -> dict[str, pl.DataFrame]:
        """Run all extraction patterns and return combined raw staging data."""

        raw: dict[str, pl.DataFrame] = {}
        if not game_log_df.is_empty():
            raw["stg_league_game_log"] = game_log_df

        step = 0
        total_steps = 6

        # Static
        static_entries = get_by_pattern("static")
        if static_entries:
            step += 1
            logger.info("Step {}/{}: extracting static endpoints", step, total_steps)
            static_raw = await runner.run_pattern("static", [{}], static_entries)
            raw.update(static_raw)

        # Season (skip league_game_log -- already extracted)
        season_entries = [
            e for e in get_by_pattern("season") if e.endpoint_name != "league_game_log"
        ]
        if season_entries and seasons:
            step += 1
            logger.info("Step {}/{}: extracting season endpoints", step, total_steps)
            season_params = [{"season": s} for s in seasons]
            season_raw = await runner.run_pattern("season", season_params, season_entries)
            raw.update(season_raw)

        # Game (chunked internally by runner)
        game_entries = get_by_pattern("game")
        if game_entries and game_ids:
            step += 1
            logger.info("Step {}/{}: extracting game endpoints", step, total_steps)
            game_params = [{"game_id": gid} for gid in game_ids]
            game_raw = await runner.run_pattern("game", game_params, game_entries)
            raw.update(game_raw)

        # Player
        player_entries = get_by_pattern("player")
        if player_entries and player_ids:
            step += 1
            logger.info("Step {}/{}: extracting player endpoints", step, total_steps)
            player_params = [{"player_id": pid} for pid in player_ids]
            player_raw = await runner.run_pattern("player", player_params, player_entries)
            raw.update(player_raw)

        # Team
        team_entries = get_by_pattern("team")
        if team_entries and team_ids:
            step += 1
            logger.info("Step {}/{}: extracting team endpoints", step, total_steps)
            team_params = [{"team_id": tid} for tid in team_ids]
            team_raw = await runner.run_pattern("team", team_params, team_entries)
            raw.update(team_raw)

        # Date
        date_entries = get_by_pattern("date")
        if date_entries and game_dates:
            step += 1
            logger.info("Step {}/{}: extracting date endpoints", step, total_steps)
            date_params = [{"game_date": d} for d in game_dates]
            date_raw = await runner.run_pattern("date", date_params, date_entries)
            raw.update(date_raw)

        return raw

    # ── run modes ──────────────────────────────────────────────

    async def run_init(
        self,
        start_season: int = 1946,
    ) -> PipelineResult:
        """Full history build from scratch with resume support.

        Resume logic works automatically:
        - Each extraction checks ``journal.was_extracted()``
        - If interrupted, re-running skips all successful work
        - Failed extractions are retried
        """
        bound_log = logger.bind(run_mode="init")
        t0 = time.perf_counter()

        import polars as pl

        db, journal = self._init_db()
        runner = self._build_runner(journal)

        # -- 1. Entity discovery (parallel) --------------------
        seasons = season_range(start_season)
        discovery = self._build_discovery()

        bound_log.info(
            "init: discovering entities for {} seasons",
            len(seasons),
        )

        results = await asyncio.gather(
            discovery.discover_game_ids(seasons),
            discovery.discover_player_ids(),
            discovery.discover_team_ids(),
            return_exceptions=True,
        )
        _game_result = results[0]
        _player_result = results[1]
        _team_result = results[2]

        if isinstance(_game_result, Exception):
            bound_log.warning("discover_game_ids failed: {}", type(_game_result).__name__)
            game_ids: list[str] = []
            game_log_df = pl.DataFrame()
        else:
            game_ids, game_log_df = _game_result

        if isinstance(_player_result, Exception):
            bound_log.warning("discover_player_ids failed: {}", type(_player_result).__name__)
            player_ids: list[int] = []
        else:
            player_ids = _player_result

        if isinstance(_team_result, Exception):
            bound_log.warning("discover_team_ids failed: {}", type(_team_result).__name__)
            team_ids: list[int] = []
        else:
            team_ids = _team_result

        game_dates = await discovery.discover_game_dates(game_log_df)

        bound_log.info(
            "discovered: {} games, {} players, {} teams, {} dates",
            len(game_ids),
            len(player_ids),
            len(team_ids),
            len(game_dates),
        )

        # -- 2. Extract by pattern ------------------------------
        raw = await self._extract_all_patterns(
            runner,
            seasons=seasons,
            game_ids=game_ids,
            player_ids=player_ids,
            team_ids=team_ids,
            game_dates=game_dates,
            game_log_df=game_log_df,
        )

        # -- 3. Transform + Load --------------------------------
        bound_log.info("transform + load: {} staging tables", len(raw))
        tables_updated, rows_total, failed_loads = self._transform_and_load(
            db, raw, journal, mode="replace"
        )

        # -- 4. Summarize result --------------------------------
        result = self._build_result(
            t0,
            tables_updated,
            rows_total,
            failed_loads,
            journal=journal,
        )
        result.skipped_extractions = runner.skipped

        bound_log.info(
            "init complete: {} tables, {} rows, {:.1f}s, {} extract failures, {} load failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
            result.failed_loads,
        )
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
        runner = self._build_runner(journal)
        discovery = self._build_discovery()

        season = current_season()
        bound_log.info("daily: season={}", season)

        # -- 1. Discover recent game_ids ------------------------
        game_ids, game_log_df = await discovery.discover_game_ids([season])

        raw: dict[str, pl.DataFrame] = {}
        if not game_log_df.is_empty():
            raw["stg_league_game_log"] = game_log_df

        # Filter to recent dates
        if not game_log_df.is_empty() and "game_date" in game_log_df.columns:
            from datetime import datetime, timedelta

            cutoff = (datetime.now() - timedelta(days=self._settings.daily_lookback_days)).strftime(
                "%Y-%m-%d"
            )
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

        # -- 2. Game + season + date extraction via shared helper
        # (no player/team/static for daily)
        raw.update(
            await self._extract_all_patterns(
                runner,
                seasons=[season],
                game_ids=game_ids,
                player_ids=[],
                team_ids=[],
                game_dates=game_dates,
                game_log_df=pl.DataFrame(),  # already seeded above
            )
        )
        # Keep the seeded game_log_df (update may have cleared it)
        if not game_log_df.is_empty():
            raw.setdefault("stg_league_game_log", game_log_df)

        # -- 3. Transform + Load --------------------------------
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

        import polars as pl

        db, journal = self._init_db()
        runner = self._build_runner(journal)
        discovery = self._build_discovery()

        seasons = recent_seasons(3)
        bound_log.info("monthly: seasons={}", seasons)

        # -- 1. Discover entities (parallel) -------------------
        results = await asyncio.gather(
            discovery.discover_game_ids(seasons),
            discovery.discover_player_ids(),
            discovery.discover_team_ids(),
            return_exceptions=True,
        )
        _game_result = results[0]
        _player_result = results[1]
        _team_result = results[2]

        if isinstance(_game_result, Exception):
            bound_log.warning("discover_game_ids failed: {}", type(_game_result).__name__)
            game_ids: list[str] = []
            game_log_df = pl.DataFrame()
        else:
            game_ids, game_log_df = _game_result

        if isinstance(_player_result, Exception):
            bound_log.warning("discover_player_ids failed: {}", type(_player_result).__name__)
            player_ids: list[int] = []
        else:
            player_ids = _player_result

        if isinstance(_team_result, Exception):
            bound_log.warning("discover_team_ids failed: {}", type(_team_result).__name__)
            team_ids: list[int] = []
        else:
            team_ids = _team_result

        game_dates = await discovery.discover_game_dates(game_log_df)

        # -- 2. Extract all patterns ----------------------------
        raw = await self._extract_all_patterns(
            runner,
            seasons=seasons,
            game_ids=game_ids,
            player_ids=player_ids,
            team_ids=team_ids,
            game_dates=game_dates,
            game_log_df=game_log_df,
        )

        # -- 3. Transform + Load --------------------------------
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
        runner = self._build_runner(journal)
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
            params = json.loads(params_json)
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

        # -- 2. Check watermarks for missing seasons ------------
        seasons = season_range()
        season_entries = get_by_pattern("season")
        season_params = [{"season": s} for s in seasons]

        # Runner will skip already-extracted via journal
        if season_entries:
            bound_log.info(
                "full: checking {} seasons for gaps",
                len(seasons),
            )
            season_raw = await runner.run_pattern("season", season_params, season_entries)
            raw.update(season_raw)

        # Discover entities for any game-level gaps
        game_ids, game_log_df = await discovery.discover_game_ids(seasons)
        if not game_log_df.is_empty():
            raw.setdefault("stg_league_game_log", game_log_df)

        game_entries = get_by_pattern("game")
        if game_entries and game_ids:
            game_params = [{"game_id": gid} for gid in game_ids]
            bound_log.info(
                "full: checking {} games for gaps",
                len(game_ids),
            )
            game_raw = await runner.run_pattern("game", game_params, game_entries)
            raw.update(game_raw)

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

        bound_log.info(
            "full complete: {} tables, {} rows, {:.1f}s, {} remaining failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
        )
        return result
