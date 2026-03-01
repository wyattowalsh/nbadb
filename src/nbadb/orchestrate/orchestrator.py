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
    errors: list[str] = field(default_factory=list)


class Orchestrator:
    """Main orchestration engine.

    Coordinates extraction, transformation, and loading across
    all pipeline run modes (init, daily, monthly, full).

    Resume logic is handled automatically via the extraction
    journal -- each call checks ``journal.was_extracted()``
    before invoking an endpoint.
    """

    def __init__(
        self, settings: NbaDbSettings | None = None
    ) -> None:
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

        self._db = db
        self._journal = journal
        return db, journal

    def _build_runner(
        self, journal: PipelineJournal
    ) -> ExtractorRunner:
        _global_registry.discover()
        return ExtractorRunner(
            registry=_global_registry,
            settings=self._settings,
            journal=journal,
            proxy_pool=self._proxy_pool,
        )

    def _transform_and_load(
        self,
        db: DBManager,
        raw: dict[str, pl.DataFrame],
        journal: PipelineJournal,
        mode: str = "replace",
    ) -> tuple[int, int]:
        """Run transform pipeline then load all outputs.

        Returns (tables_updated, rows_total).
        """
        # Build staging dict (LazyFrames)
        staging: dict[str, pl.LazyFrame] = {
            key: df.lazy() for key, df in raw.items()
        }

        # Transform
        transformers = discover_all_transformers()
        pipeline = TransformPipeline(db.duckdb)
        pipeline.register_all(transformers)
        outputs = pipeline.run(staging)

        # Load
        loader = create_multi_loader(
            self._settings, duckdb_conn=db.duckdb
        )
        tables_updated = 0
        rows_total = 0

        for table, df in outputs.items():
            if df.is_empty():
                logger.debug("skip load (empty): {}", table)
                continue
            try:
                loader.load(table, df, mode=mode)  # type: ignore[arg-type]
                rows = df.shape[0]
                tables_updated += 1
                rows_total += rows
                journal.set_watermark(
                    table, "last_load", current_season(), rows
                )
                logger.info(
                    "loaded {}: {} rows ({})",
                    table,
                    rows,
                    mode,
                )
            except Exception as exc:
                logger.error(
                    "load failed for {}: {}", table, exc
                )

        return tables_updated, rows_total

    # ── run modes ──────────────────────────────────────────────

    async def run_init(
        self, start_season: int = 1946
    ) -> PipelineResult:
        """Full history build from scratch with resume support.

        Resume logic works automatically:
        - Each extraction checks ``journal.was_extracted()``
        - If interrupted, re-running skips all successful work
        - Failed extractions are retried
        """
        t0 = time.perf_counter()
        result = PipelineResult()

        db, journal = self._init_db()
        runner = self._build_runner(journal)

        # -- 1. Entity discovery --------------------------------
        seasons = season_range(start_season)
        discovery = EntityDiscovery(
            _global_registry, proxy_pool=self._proxy_pool
        )

        logger.info(
            "init: discovering entities for {} seasons",
            len(seasons),
        )

        game_ids, game_log_df = (
            await discovery.discover_game_ids(seasons)
        )
        await asyncio.sleep(1.0)
        player_ids = await discovery.discover_player_ids()
        await asyncio.sleep(1.0)
        team_ids = await discovery.discover_team_ids()
        game_dates = await discovery.discover_game_dates(
            game_log_df
        )

        logger.info(
            "discovered: {} games, {} players, {} teams, "
            "{} dates",
            len(game_ids),
            len(player_ids),
            len(team_ids),
            len(game_dates),
        )

        # -- 2. Extract by pattern ------------------------------
        raw: dict[str, pl.DataFrame] = {}

        # Seed with game_log_df (already extracted via discovery)
        if not game_log_df.is_empty():
            raw["stg_league_game_log"] = game_log_df

        # Static
        static_entries = get_by_pattern("static")
        if static_entries:
            logger.info("extracting static endpoints")
            static_raw = await runner.run_pattern(
                "static", [{}], static_entries
            )
            raw.update(static_raw)

        # Season (skip league_game_log -- already extracted)
        season_entries = [
            e
            for e in get_by_pattern("season")
            if e.endpoint_name != "league_game_log"
        ]
        if season_entries:
            season_params = [{"season": s} for s in seasons]
            logger.info(
                "extracting {} season endpoints x {} seasons",
                len(season_entries),
                len(seasons),
            )
            season_raw = await runner.run_pattern(
                "season", season_params, season_entries
            )
            raw.update(season_raw)

        # Game (chunked internally by runner)
        game_entries = get_by_pattern("game")
        if game_entries and game_ids:
            game_params = [{"game_id": gid} for gid in game_ids]
            logger.info(
                "extracting {} game endpoints x {} games",
                len(game_entries),
                len(game_ids),
            )
            game_raw = await runner.run_pattern(
                "game", game_params, game_entries
            )
            raw.update(game_raw)

        # Player
        player_entries = get_by_pattern("player")
        if player_entries and player_ids:
            player_params = [
                {"player_id": pid} for pid in player_ids
            ]
            logger.info(
                "extracting {} player endpoints x {} players",
                len(player_entries),
                len(player_ids),
            )
            player_raw = await runner.run_pattern(
                "player", player_params, player_entries
            )
            raw.update(player_raw)

        # Team
        team_entries = get_by_pattern("team")
        if team_entries and team_ids:
            team_params = [{"team_id": tid} for tid in team_ids]
            logger.info(
                "extracting {} team endpoints x {} teams",
                len(team_entries),
                len(team_ids),
            )
            team_raw = await runner.run_pattern(
                "team", team_params, team_entries
            )
            raw.update(team_raw)

        # Date
        date_entries = get_by_pattern("date")
        if date_entries and game_dates:
            date_params = [
                {"game_date": d} for d in game_dates
            ]
            logger.info(
                "extracting {} date endpoints x {} dates",
                len(date_entries),
                len(game_dates),
            )
            date_raw = await runner.run_pattern(
                "date", date_params, date_entries
            )
            raw.update(date_raw)

        # -- 3. Transform + Load --------------------------------
        logger.info(
            "transform + load: {} staging tables", len(raw)
        )
        tables_updated, rows_total = self._transform_and_load(
            db, raw, journal, mode="replace"
        )

        # -- 4. Summarize result --------------------------------
        failed = journal.get_failed()
        result.tables_updated = tables_updated
        result.rows_total = rows_total
        result.failed_extractions = len(failed)
        result.errors = [
            f"{ep}[{p}]: {err}" for ep, p, err in failed
        ]
        result.duration_seconds = time.perf_counter() - t0

        logger.info(
            "init complete: {} tables, {} rows, "
            "{:.1f}s, {} failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
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

        t0 = time.perf_counter()
        result = PipelineResult()

        db, journal = self._init_db()
        runner = self._build_runner(journal)
        discovery = EntityDiscovery(
            _global_registry, proxy_pool=self._proxy_pool
        )

        season = current_season()
        logger.info("daily: season={}", season)

        # -- 1. Discover recent game_ids ------------------------
        game_ids, game_log_df = (
            await discovery.discover_game_ids([season])
        )

        raw: dict[str, pl.DataFrame] = {}
        if not game_log_df.is_empty():
            raw["stg_league_game_log"] = game_log_df

        # Filter to recent dates
        if not game_log_df.is_empty() and "game_date" in game_log_df.columns:
            from datetime import datetime, timedelta

            cutoff = (
                datetime.now()
                - timedelta(
                    days=self._settings.daily_lookback_days
                )
            ).strftime("%Y-%m-%d")
            recent = game_log_df.filter(
                pl.col("game_date").cast(pl.Utf8) >= cutoff
            )
            game_ids = (
                recent.get_column("game_id")
                .unique()
                .sort()
                .to_list()
            )
            game_dates = (
                recent.get_column("game_date")
                .cast(pl.Utf8)
                .unique()
                .sort()
                .to_list()
            )
        else:
            game_dates = []

        logger.info(
            "daily: {} recent games, {} dates",
            len(game_ids),
            len(game_dates),
        )

        # -- 2. Game-level extraction ---------------------------
        game_entries = get_by_pattern("game")
        if game_entries and game_ids:
            game_params = [{"game_id": gid} for gid in game_ids]
            game_raw = await runner.run_pattern(
                "game", game_params, game_entries
            )
            raw.update(game_raw)

        # -- 3. Season-level refresh ----------------------------
        season_entries = [
            e
            for e in get_by_pattern("season")
            if e.endpoint_name != "league_game_log"
        ]
        if season_entries:
            season_raw = await runner.run_pattern(
                "season", [{"season": season}], season_entries
            )
            raw.update(season_raw)

        # -- 4. Date-level extraction ---------------------------
        date_entries = get_by_pattern("date")
        if date_entries and game_dates:
            date_params = [
                {"game_date": d} for d in game_dates
            ]
            date_raw = await runner.run_pattern(
                "date", date_params, date_entries
            )
            raw.update(date_raw)

        # -- 5. Transform + Load --------------------------------
        tables_updated, rows_total = self._transform_and_load(
            db, raw, journal, mode="replace"
        )

        failed = journal.get_failed()
        result.tables_updated = tables_updated
        result.rows_total = rows_total
        result.failed_extractions = len(failed)
        result.errors = [
            f"{ep}[{p}]: {err}" for ep, p, err in failed
        ]
        result.duration_seconds = time.perf_counter() - t0

        logger.info(
            "daily complete: {} tables, {} rows, "
            "{:.1f}s, {} failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
        )
        return result

    async def run_monthly(self) -> PipelineResult:
        """Monthly refresh of the last 3 seasons.

        Runs all pattern types for ``recent_seasons(3)`` and does
        a full replace for all tables.
        """
        t0 = time.perf_counter()
        result = PipelineResult()

        db, journal = self._init_db()
        runner = self._build_runner(journal)
        discovery = EntityDiscovery(
            _global_registry, proxy_pool=self._proxy_pool
        )

        seasons = recent_seasons(3)
        logger.info("monthly: seasons={}", seasons)

        # -- 1. Discover entities for scope ---------------------
        game_ids, game_log_df = (
            await discovery.discover_game_ids(seasons)
        )
        await asyncio.sleep(1.0)
        player_ids = await discovery.discover_player_ids()
        await asyncio.sleep(1.0)
        team_ids = await discovery.discover_team_ids()
        game_dates = await discovery.discover_game_dates(
            game_log_df
        )

        raw: dict[str, pl.DataFrame] = {}
        if not game_log_df.is_empty():
            raw["stg_league_game_log"] = game_log_df

        # -- 2. Static -----------------------------------------
        static_entries = get_by_pattern("static")
        if static_entries:
            static_raw = await runner.run_pattern(
                "static", [{}], static_entries
            )
            raw.update(static_raw)

        # -- 3. Season ------------------------------------------
        season_entries = [
            e
            for e in get_by_pattern("season")
            if e.endpoint_name != "league_game_log"
        ]
        if season_entries:
            season_params = [{"season": s} for s in seasons]
            season_raw = await runner.run_pattern(
                "season", season_params, season_entries
            )
            raw.update(season_raw)

        # -- 4. Game --------------------------------------------
        game_entries = get_by_pattern("game")
        if game_entries and game_ids:
            game_params = [{"game_id": gid} for gid in game_ids]
            game_raw = await runner.run_pattern(
                "game", game_params, game_entries
            )
            raw.update(game_raw)

        # -- 5. Player ------------------------------------------
        player_entries = get_by_pattern("player")
        if player_entries and player_ids:
            player_params = [
                {"player_id": pid} for pid in player_ids
            ]
            player_raw = await runner.run_pattern(
                "player", player_params, player_entries
            )
            raw.update(player_raw)

        # -- 6. Team --------------------------------------------
        team_entries = get_by_pattern("team")
        if team_entries and team_ids:
            team_params = [{"team_id": tid} for tid in team_ids]
            team_raw = await runner.run_pattern(
                "team", team_params, team_entries
            )
            raw.update(team_raw)

        # -- 7. Date --------------------------------------------
        date_entries = get_by_pattern("date")
        if date_entries and game_dates:
            date_params = [
                {"game_date": d} for d in game_dates
            ]
            date_raw = await runner.run_pattern(
                "date", date_params, date_entries
            )
            raw.update(date_raw)

        # -- 8. Transform + Load --------------------------------
        tables_updated, rows_total = self._transform_and_load(
            db, raw, journal, mode="replace"
        )

        failed = journal.get_failed()
        result.tables_updated = tables_updated
        result.rows_total = rows_total
        result.failed_extractions = len(failed)
        result.errors = [
            f"{ep}[{p}]: {err}" for ep, p, err in failed
        ]
        result.duration_seconds = time.perf_counter() - t0

        logger.info(
            "monthly complete: {} tables, {} rows, "
            "{:.1f}s, {} failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
        )
        return result

    async def run_full(self) -> PipelineResult:
        """Fill gaps and retry all failed extractions.

        1. Read journal for failed/incomplete extractions
        2. Retry those extractions
        3. Check watermarks for missing seasons
        4. Transform + load
        """
        t0 = time.perf_counter()
        result = PipelineResult()

        db, journal = self._init_db()
        runner = self._build_runner(journal)
        discovery = EntityDiscovery(
            _global_registry, proxy_pool=self._proxy_pool
        )

        # -- 1. Retry failed extractions ------------------------
        failed = journal.get_failed()
        logger.info(
            "full: {} failed extractions to retry",
            len(failed),
        )

        # Group failed by pattern for batched re-extraction
        failed_by_entry: dict[
            str, list[dict]
        ] = {}  # endpoint -> params
        for endpoint, params_json, _error in failed:
            params = json.loads(params_json)
            failed_by_entry.setdefault(endpoint, []).append(
                params
            )

        # Build a lookup from endpoint_name -> StagingEntry(s)
        entries_by_ep: dict[str, list] = {}
        for entry in STAGING_MAP:
            entries_by_ep.setdefault(
                entry.endpoint_name, []
            ).append(entry)

        raw: dict[str, pl.DataFrame] = {}

        for endpoint, param_list in failed_by_entry.items():
            ep_entries = entries_by_ep.get(endpoint, [])
            if not ep_entries:
                logger.warning(
                    "no staging entry for failed endpoint: {}",
                    endpoint,
                )
                continue
            pattern = ep_entries[0].param_pattern
            retry_raw = await runner.run_pattern(
                pattern, param_list, ep_entries
            )
            raw.update(retry_raw)

        # -- 2. Check watermarks for missing seasons ------------
        seasons = season_range()
        season_entries = get_by_pattern("season")
        season_params = [{"season": s} for s in seasons]

        # Runner will skip already-extracted via journal
        if season_entries:
            logger.info(
                "full: checking {} seasons for gaps",
                len(seasons),
            )
            season_raw = await runner.run_pattern(
                "season", season_params, season_entries
            )
            raw.update(season_raw)

        # Discover entities for any game-level gaps
        game_ids, game_log_df = (
            await discovery.discover_game_ids(seasons)
        )
        if not game_log_df.is_empty():
            raw.setdefault(
                "stg_league_game_log", game_log_df
            )

        game_entries = get_by_pattern("game")
        if game_entries and game_ids:
            game_params = [{"game_id": gid} for gid in game_ids]
            logger.info(
                "full: checking {} games for gaps",
                len(game_ids),
            )
            game_raw = await runner.run_pattern(
                "game", game_params, game_entries
            )
            raw.update(game_raw)

        # -- 3. Transform + Load --------------------------------
        if raw:
            tables_updated, rows_total = (
                self._transform_and_load(
                    db, raw, journal, mode="replace"
                )
            )
            result.tables_updated = tables_updated
            result.rows_total = rows_total

        remaining_failed = journal.get_failed()
        result.failed_extractions = len(remaining_failed)
        result.errors = [
            f"{ep}[{p}]: {err}"
            for ep, p, err in remaining_failed
        ]
        result.duration_seconds = time.perf_counter() - t0

        logger.info(
            "full complete: {} tables, {} rows, "
            "{:.1f}s, {} remaining failures",
            result.tables_updated,
            result.rows_total,
            result.duration_seconds,
            result.failed_extractions,
        )
        return result
