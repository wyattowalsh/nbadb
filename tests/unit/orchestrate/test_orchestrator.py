"""Tests for nbadb.orchestrate.orchestrator.Orchestrator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl

from nbadb.orchestrate.orchestrator import Orchestrator, PipelineResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_settings():
    s = MagicMock()
    s.duckdb_path = MagicMock()
    s.duckdb_path.exists.return_value = True
    s.sqlite_path = MagicMock()
    s.semaphore_tiers = {"default": 5}
    s.proxy_semaphore_multiplier = 1.0
    s.pbp_chunk_size = 50
    s.proxy_urls = []
    s.daily_lookback_days = 7
    return s


# Common patch targets
_PROXY = "nbadb.orchestrate.orchestrator.build_proxy_pool"
_DB_MANAGER = "nbadb.orchestrate.orchestrator.DBManager"
_JOURNAL = "nbadb.orchestrate.orchestrator.PipelineJournal"
_REGISTRY = "nbadb.orchestrate.orchestrator._global_registry"
_DISCOVERY = "nbadb.orchestrate.orchestrator.EntityDiscovery"
_RUNNER = "nbadb.orchestrate.orchestrator.ExtractorRunner"
_TRANSFORMERS = "nbadb.orchestrate.orchestrator.discover_all_transformers"
_PIPELINE = "nbadb.orchestrate.orchestrator.TransformPipeline"
_LOADER = "nbadb.orchestrate.orchestrator.create_multi_loader"
_SEASON_RANGE = "nbadb.orchestrate.orchestrator.season_range"
_CURRENT_SEASON = "nbadb.orchestrate.orchestrator.current_season"
_RECENT_SEASONS = "nbadb.orchestrate.orchestrator.recent_seasons"


def _build_orchestrator_with_mocks():
    """Set up Orchestrator with all external deps mocked."""
    settings = _mock_settings()

    with patch(_PROXY, return_value=None):
        orch = Orchestrator(settings=settings)

    # Mock DB + Journal
    db = MagicMock()
    db.duckdb = MagicMock()
    journal = MagicMock()
    journal.get_failed.return_value = []
    journal.set_watermark = MagicMock()

    orch._db = db
    orch._journal = journal

    return orch, db, journal


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
    def test_creates_without_proxy(self):
        settings = _mock_settings()
        with patch(_PROXY, return_value=None):
            orch = Orchestrator(settings=settings)
        assert orch._proxy_pool is None

    def test_creates_with_proxy(self):
        settings = _mock_settings()
        mock_pool = MagicMock()
        with patch(_PROXY, return_value=mock_pool):
            orch = Orchestrator(settings=settings)
        assert orch._proxy_pool is mock_pool


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
        with patch(_PROXY, return_value=None):
            orch = Orchestrator(settings=settings)

        mock_db = MagicMock()
        mock_db.duckdb = MagicMock()
        with (
            patch(_DB_MANAGER, return_value=mock_db),
            patch(_JOURNAL, return_value=MagicMock()),
        ):
            db, journal = orch._init_db()

        mock_db.init.assert_called_once()
        assert orch._db is mock_db


# ---------------------------------------------------------------------------
# _transform_and_load tests
# ---------------------------------------------------------------------------


class TestTransformAndLoad:
    def test_loads_non_empty_outputs(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        raw = {"stg_test": pl.DataFrame({"a": [1, 2]})}
        mock_outputs = {"dim_test": pl.DataFrame({"b": [3, 4, 5]})}

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = mock_outputs
        mock_loader = MagicMock()

        with (
            patch(_TRANSFORMERS, return_value=[]),
            patch(_PIPELINE, return_value=mock_pipeline),
            patch(_LOADER, return_value=mock_loader),
            patch(_CURRENT_SEASON, return_value="2024-25"),
        ):
            tables, rows, failed = orch._transform_and_load(db, raw, journal)

        assert tables == 1
        assert rows == 3
        assert failed == 0
        mock_loader.load.assert_called_once()

    def test_skips_empty_outputs(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        raw = {"stg_test": pl.DataFrame({"a": [1]})}
        mock_outputs = {"dim_empty": pl.DataFrame()}

        mock_pipeline = MagicMock()
        mock_pipeline.run.return_value = mock_outputs
        mock_loader = MagicMock()

        with (
            patch(_TRANSFORMERS, return_value=[]),
            patch(_PIPELINE, return_value=mock_pipeline),
            patch(_LOADER, return_value=mock_loader),
            patch(_CURRENT_SEASON, return_value="2024-25"),
        ):
            tables, rows, failed = orch._transform_and_load(db, raw, journal)

        assert tables == 0
        assert rows == 0
        mock_loader.load.assert_not_called()

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
            patch(_PIPELINE, return_value=mock_pipeline),
            patch(_LOADER, return_value=mock_loader),
            patch(_CURRENT_SEASON, return_value="2024-25"),
        ):
            tables, rows, failed = orch._transform_and_load(db, raw, journal)

        assert tables == 0
        assert failed == 1


# ---------------------------------------------------------------------------
# run_init tests
# ---------------------------------------------------------------------------


class TestRunInit:
    def test_run_init_returns_pipeline_result(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = (
            ["0022400001"],
            pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2024-10-22"]}),
        )
        mock_discovery.discover_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]

        mock_runner = MagicMock()
        mock_runner.run_pattern = AsyncMock(return_value={})

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(2, 100, 0)),
        ):
            result = asyncio.run(orch.run_init())

        assert isinstance(result, PipelineResult)
        assert result.tables_updated == 2
        assert result.rows_total == 100
        assert result.duration_seconds > 0


# ---------------------------------------------------------------------------
# run_daily tests
# ---------------------------------------------------------------------------


class TestRunDaily:
    def test_run_daily_returns_pipeline_result(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = (["0022400001"], game_log_df)

        mock_runner = MagicMock()
        mock_runner.run_pattern = AsyncMock(return_value={})

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)),
        ):
            result = asyncio.run(orch.run_daily())

        assert isinstance(result, PipelineResult)
        assert result.tables_updated == 1


# ---------------------------------------------------------------------------
# run_full tests
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# run_monthly tests
# ---------------------------------------------------------------------------


class TestRunMonthly:
    def test_run_monthly_returns_pipeline_result(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = (["0022400001"], game_log_df)
        mock_discovery.discover_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2026-02-28"]

        mock_runner = MagicMock()
        mock_runner.run_pattern = AsyncMock(return_value={})
        mock_runner.skipped = 0

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_RECENT_SEASONS, return_value=["2023-24", "2024-25", "2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)),
        ):
            result = asyncio.run(orch.run_monthly())

        assert isinstance(result, PipelineResult)
        assert result.tables_updated == 1

    def test_run_monthly_sets_duration(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = ([], pl.DataFrame())
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []

        mock_runner = MagicMock()
        mock_runner.run_pattern = AsyncMock(return_value={})
        mock_runner.skipped = 0

        with (
            patch(_RECENT_SEASONS, return_value=["2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(0, 0, 0)),
        ):
            result = asyncio.run(orch.run_monthly())

        assert isinstance(result, PipelineResult)
        assert result.duration_seconds >= 0


# ---------------------------------------------------------------------------
# run_full tests
# ---------------------------------------------------------------------------


class TestRunFull:
    def test_retries_failed_extractions(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        # First call returns failures, second call (after retry) returns empty
        journal.get_failed.side_effect = [
            [("ep1", '{"season": "2024-25"}', "TimeoutError")],
            [],
        ]

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = ([], pl.DataFrame())

        mock_runner = MagicMock()
        mock_runner.run_pattern = AsyncMock(return_value={})

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(0, 0, 0)),
        ):
            result = asyncio.run(orch.run_full())

        assert isinstance(result, PipelineResult)
        assert result.failed_extractions == 0
