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
    s.default_chunk_size = 500
    s.thread_pool_size = 4
    s.rate_limit = 10.0
    s.adaptive_rate_min = 1.0
    s.adaptive_rate_recovery = 50
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
_GET_BY_PATTERN = "nbadb.orchestrate.planning.get_by_pattern"
_SEASON_RANGE = "nbadb.orchestrate.orchestrator.season_range"
_CURRENT_SEASON = "nbadb.orchestrate.orchestrator.current_season"
_RECENT_SEASONS = "nbadb.orchestrate.orchestrator.recent_seasons"


def _mock_runner(**overrides):
    """Create a MagicMock runner that supports ``async with``."""
    runner = MagicMock()
    runner.run_pattern = AsyncMock(return_value={})
    runner.__aenter__ = AsyncMock(return_value=runner)
    runner.__aexit__ = AsyncMock(return_value=False)
    for k, v in overrides.items():
        setattr(runner, k, v)
    return runner


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
    journal.has_done_entries.return_value = False
    journal.clear_journal = MagicMock()

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
        assert mock_pipeline.run.call_args.kwargs["validate_input_schemas"] is True

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
        assert mock_pipeline.run.call_args.kwargs["validate_input_schemas"] is True

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
        assert mock_pipeline.run.call_args.kwargs["validate_input_schemas"] is True


# ---------------------------------------------------------------------------
# _extract_all_patterns tests
# ---------------------------------------------------------------------------


class TestExtractAllPatterns:
    def test_patterns_run_in_priority_order(self):
        """Patterns execute in priority tiers: static/season before game."""
        orch, db, journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        call_order: list[str] = []

        async def track_pattern(pattern, params, entries, on_progress=None):
            call_order.append(pattern)
            return {}

        runner.run_pattern = AsyncMock(side_effect=track_pattern)

        static_entries = [MagicMock(endpoint_name="league_standings")]
        season_entries = [MagicMock(endpoint_name="league_game_log")]
        season_entries[0].endpoint_name = "common_team_roster"
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

        with patch(_GET_BY_PATTERN, side_effect=_entries):
            asyncio.run(
                orch._extract_all_patterns(
                    runner,
                    seasons=["2024-25"],
                    game_ids=["0022400001"],
                    player_ids=[],
                    team_ids=[],
                    game_dates=[],
                    game_log_df=pl.DataFrame(),
                )
            )

        # Static (tier 0) must come before season (tier 1) which must
        # come before game (tier 4)
        assert call_order.index("static") < call_order.index("season")
        assert call_order.index("season") < call_order.index("game")

    def test_extracts_player_team_season_cross_product_patterns(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        runner.run_pattern = AsyncMock(return_value={})

        player_season_entries = [MagicMock(endpoint_name="player_game_log")]
        player_team_season_entries = [MagicMock(endpoint_name="video_details")]
        team_season_entries = [MagicMock(endpoint_name="team_game_log")]

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

        with patch(_GET_BY_PATTERN, side_effect=_entries):
            asyncio.run(
                orch._extract_all_patterns(
                    runner,
                    seasons=["2024-25", "2025-26"],
                    game_ids=[],
                    player_ids=[201939, 2544],
                    team_ids=[1610612744],
                    game_dates=[],
                    player_team_season_params=[
                        {"player_id": 201939, "team_id": 1610612744, "season": "2024-25"},
                        {"player_id": 2544, "team_id": 1610612747, "season": "2025-26"},
                    ],
                    game_log_df=pl.DataFrame(),
                )
            )

        runner.run_pattern.assert_any_await(
            "player_season",
            [
                {"player_id": 201939, "season": "2024-25"},
                {"player_id": 201939, "season": "2025-26"},
                {"player_id": 2544, "season": "2024-25"},
                {"player_id": 2544, "season": "2025-26"},
            ],
            player_season_entries,
            on_progress=None,
        )
        runner.run_pattern.assert_any_await(
            "team_season",
            [
                {"team_id": 1610612744, "season": "2024-25"},
                {"team_id": 1610612744, "season": "2025-26"},
            ],
            team_season_entries,
            on_progress=None,
        )
        runner.run_pattern.assert_any_await(
            "player_team_season",
            [
                {"player_id": 201939, "team_id": 1610612744, "season": "2024-25"},
                {"player_id": 2544, "team_id": 1610612747, "season": "2025-26"},
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
        mock_discovery.discover_game_ids.return_value = (
            ["0022400001"],
            pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2024-10-22"]}),
        )
        mock_discovery.discover_all_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params.return_value = []

        mock_runner = _mock_runner()

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

    def test_run_init_resumes_when_journal_has_done_entries(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        journal.has_done_entries.return_value = True

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = (
            ["0022400001"],
            pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2024-10-22"]}),
        )
        mock_discovery.discover_all_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params.return_value = []

        mock_runner = _mock_runner()

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(2, 100, 0)),
        ):
            asyncio.run(orch.run_init())

        # Journal should NOT be cleared — resume skips done entries
        journal.clear_journal.assert_not_called()


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
        mock_discovery.discover_player_team_season_params.return_value = []

        mock_runner = _mock_runner()

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

    def test_run_daily_disables_static_in_shared_helper(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        game_log_df = pl.DataFrame(
            {
                "game_id": ["0022400001"],
                "game_date": ["2026-02-28"],
            }
        )
        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = (["0022400001"], game_log_df)
        mock_discovery.discover_player_team_season_params.return_value = []

        mock_runner = _mock_runner(skipped=0)
        mock_extract = AsyncMock(return_value={})

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)),
        ):
            asyncio.run(orch.run_daily())

        assert mock_extract.await_args.kwargs["include_static"] is False

    def test_run_daily_loads_persisted_staging_when_extraction_is_empty(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = ([], pl.DataFrame())
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_player_team_season_params.return_value = []

        recovered_raw = {
            "stg_league_game_log": pl.DataFrame(
                {"game_id": ["0022400001"], "game_date": ["2026-02-28"]}
            )
        }
        mock_runner = _mock_runner(skipped=1)
        mock_extract = AsyncMock(return_value={})

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
        ):
            result = asyncio.run(orch.run_daily())

        mock_load.assert_called_once_with(db)
        assert mock_transform.call_args.args[1] is recovered_raw
        assert result.tables_updated == 1


# ---------------------------------------------------------------------------
# run_retry tests
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
        mock_discovery.discover_player_team_season_params.return_value = []

        mock_runner = _mock_runner(skipped=0)

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
        mock_discovery.discover_player_team_season_params.return_value = []

        mock_runner = _mock_runner(skipped=0)

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

    def test_run_monthly_loads_persisted_staging_when_extraction_is_empty(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = ([], pl.DataFrame())
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params.return_value = []

        recovered_raw = {
            "stg_league_game_log": pl.DataFrame(
                {"game_id": ["0022400001"], "game_date": ["2026-02-28"]}
            )
        }
        mock_runner = _mock_runner(skipped=1)
        mock_extract = AsyncMock(return_value={})

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
        ):
            result = asyncio.run(orch.run_monthly())

        mock_load.assert_called_once_with(db)
        assert mock_transform.call_args.args[1] is recovered_raw
        assert result.tables_updated == 1


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
        mock_discovery.discover_game_ids.return_value = ([], pl.DataFrame())
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params.return_value = []

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
        mock_runner.run_pattern.assert_awaited_once()
        assert mock_runner.run_pattern.await_args.args[0] == "season"
        assert mock_runner.run_pattern.await_args.args[1] == [{"season": "2024-25"}]

    def test_run_retry_loads_persisted_staging_when_extraction_is_empty(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = ([], pl.DataFrame())
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params.return_value = []

        recovered_raw = {
            "stg_league_game_log": pl.DataFrame(
                {"game_id": ["0022400001"], "game_date": ["2026-02-28"]}
            )
        }
        mock_runner = _mock_runner(skipped=1)
        mock_extract = AsyncMock(return_value={})

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
            [("ep1", '{"season": "2024-25"}', "TimeoutError")],
            [],
        ]

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids.return_value = ([], pl.DataFrame())
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params.return_value = []

        mock_runner = _mock_runner()

        with (
            patch(_SEASON_RANGE, return_value=["2024-25"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(0, 0, 0)),
        ):
            result = asyncio.run(orch.run_retry())

        assert isinstance(result, PipelineResult)
        assert result.failed_extractions == 0
