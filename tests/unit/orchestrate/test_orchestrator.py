"""Tests for nbadb.orchestrate.orchestrator.Orchestrator."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import duckdb
import polars as pl
import pytest

from nbadb.orchestrate.discovery import GameDiscoveryResult, PlayerTeamSeasonDiscoveryResult
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope
from nbadb.orchestrate.orchestrator import (
    ExtractionOutcome,
    Orchestrator,
    PipelineResult,
    _apply_player_shard,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_settings():
    s = MagicMock()
    s.duckdb_path = MagicMock()
    s.duckdb_path.exists.return_value = True
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


# Common patch targets
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


def _game_discovery_result(
    *,
    game_ids: list[str] | None = None,
    game_log_df: pl.DataFrame | None = None,
    seasons: tuple[str, ...] = ("2024-25",),
    season_types: tuple[str, ...] = ("Regular Season",),
    covered_combos: frozenset[tuple[str, str]] | None = None,
) -> GameDiscoveryResult:
    frame = game_log_df if game_log_df is not None else pl.DataFrame()
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


def _player_team_discovery_result(
    *,
    params: list[dict[str, int | str]] | None = None,
    seasons: tuple[str, ...] = ("2024-25",),
    season_types: tuple[str, ...] = ("Regular Season",),
    covered_pairs: frozenset[tuple[str, str]] | None = None,
) -> PlayerTeamSeasonDiscoveryResult:
    requested_pairs = frozenset(
        (season, season_type) for season in seasons for season_type in season_types
    )
    effective_covered = requested_pairs if covered_pairs is None else covered_pairs
    return PlayerTeamSeasonDiscoveryResult(
        params=params or [],
        requested_pairs=requested_pairs,
        covered_pairs=effective_covered,
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
        assert game_ids == ["001"]
        assert game_dates == ["2024-10-22"]
        assert game_log_df.shape == (1, 2)
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

        with patch(_GET_BY_PATTERN, side_effect=_entries):
            outcome = asyncio.run(
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

        assert outcome.pattern_failures == 0
        # Static (tier 0) must come before season (tier 1) which must
        # come before game (tier 4)
        assert call_order.index("static") < call_order.index("season")
        assert call_order.index("season") < call_order.index("game")

    def test_extracts_player_team_season_cross_product_patterns(self):
        orch, db, journal = _build_orchestrator_with_mocks()
        runner = MagicMock()
        runner.run_pattern = AsyncMock(return_value={})

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

        with patch(_GET_BY_PATTERN, side_effect=_entries):
            outcome = asyncio.run(
                orch._extract_all_patterns(
                    runner,
                    seasons=["2024-25", "2025-26"],
                    game_ids=[],
                    player_ids=[201939, 2544],
                    team_ids=[1610612744],
                    game_dates=[],
                    player_team_season_params=[
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
                    ],
                    game_log_df=pl.DataFrame(),
                )
            )

        assert outcome.pattern_failures == 0
        assert outcome.raw == {}
        runner.run_pattern.assert_any_await(
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
        runner.run_pattern.assert_any_await(
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
        runner.run_pattern.assert_any_await(
            "player_team_season",
            [
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
        )
        mock_discovery.discover_all_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result()
        )

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
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2024-10-22"]}),
        )
        mock_discovery.discover_all_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result()
        )

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
        )
        mock_discovery.discover_all_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result()
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

    def test_run_init_reloads_staged_batches_for_phase_b_after_current_run_failures(self):
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
        )
        mock_discovery.discover_all_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = ["2024-10-22"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result()
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
            asyncio.run(orch.run_init())

        mock_load.assert_called_once_with(db)
        assert mock_transform.call_args.args[1] == {"stg_league_game_log": game_log_df}


class TestPersistStagingToDuckdb:
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


# ---------------------------------------------------------------------------
# run_backfill tests
# ---------------------------------------------------------------------------


class TestRunBackfill:
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
        mock_runner.run_pattern.assert_awaited_once()
        assert mock_runner.run_pattern.await_args.args[0] == "season"

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
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            game_ids=["0022400001"],
            game_log_df=game_log_df,
            seasons=("2025-26",),
            season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        )
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
            )
        )

        mock_runner = _mock_runner()

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)),
            patch.object(orch, "_run_live_snapshot_upkeep", return_value=(0, 0)) as mock_live,
        ):
            result = asyncio.run(orch.run_daily())

        assert isinstance(result, PipelineResult)
        assert result.tables_updated == 1
        mock_live.assert_called_once_with(run_mode="daily")

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
            season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        )
        mock_discovery.discover_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
            )
        )

        mock_runner = _mock_runner(skipped=0)
        mock_extract = AsyncMock(return_value=ExtractionOutcome(raw={}))
        expected_season_types = [
            "Regular Season",
            "Playoffs",
            "Pre Season",
            "All Star",
        ]

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_extract_all_patterns", mock_extract),
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)),
            patch.object(orch, "_run_live_snapshot_upkeep", return_value=(2, 25)),
        ):
            result = asyncio.run(orch.run_daily())

        assert mock_discovery.discover_game_ids_result.await_args.kwargs["season_types"] == (
            expected_season_types
        )
        assert mock_extract.await_args.kwargs["season_types"] == expected_season_types
        assert result.tables_updated == 3
        assert result.rows_total == 75

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
            season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        )
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
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
            patch.object(orch, "_run_live_snapshot_upkeep", return_value=(0, 0)),
        ):
            asyncio.run(orch.run_daily())

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
            season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        )
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
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
            patch.object(orch, "_run_live_snapshot_upkeep", return_value=(0, 0)),
        ):
            result = asyncio.run(orch.run_daily())

        mock_load.assert_called_once_with(db)
        assert mock_transform.call_args.args[1] is recovered_raw
        assert result.tables_updated == 1

    def test_run_daily_reloads_staged_batches_for_phase_b_after_current_run_failure(self):
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
            season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        )
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
            )
        )

        mock_runner = _mock_runner(
            planned_calls=1,
            skipped=0,
            skipped_due_to_journal=0,
            failed_current_run=1,
        )
        mock_extract = AsyncMock(
            return_value=ExtractionOutcome(raw={"stg_league_game_log": game_log_df})
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
            patch.object(orch, "_run_live_snapshot_upkeep", return_value=(0, 0)),
        ):
            asyncio.run(orch.run_daily())

        mock_load.assert_called_once_with(db)
        assert mock_transform.call_args.args[1]["stg_league_game_log"].equals(game_log_df)

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
            season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        )
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
            )
        )

        mock_runner = _mock_runner(skipped=0)

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)),
            patch.object(orch, "_run_live_snapshot_upkeep", side_effect=RuntimeError("boom")),
        ):
            try:
                asyncio.run(orch.run_daily())
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
            season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        )
        mock_discovery.discover_player_ids.return_value = [201566]
        mock_discovery.discover_team_ids.return_value = [1610612737]
        mock_discovery.discover_game_dates.return_value = ["2026-02-28"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2023-24", "2024-25", "2025-26"),
                season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
            )
        )

        mock_runner = _mock_runner(skipped=0)

        with (
            patch(_CURRENT_SEASON, return_value="2025-26"),
            patch(_RECENT_SEASONS, return_value=["2023-24", "2024-25", "2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(1, 50, 0)),
            patch.object(orch, "_run_live_snapshot_upkeep", return_value=(0, 0)) as mock_live,
        ):
            result = asyncio.run(orch.run_monthly())

        assert isinstance(result, PipelineResult)
        assert result.tables_updated == 1
        assert mock_discovery.discover_game_ids_result.await_args.kwargs["season_types"] == [
            "Regular Season",
            "Playoffs",
            "Pre Season",
            "All Star",
        ]
        mock_live.assert_called_once_with(run_mode="monthly")

    def test_run_monthly_sets_duration(self):
        orch, db, journal = _build_orchestrator_with_mocks()

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result(
            seasons=("2025-26",),
            season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        )
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
            )
        )

        mock_runner = _mock_runner(skipped=0)

        with (
            patch(_RECENT_SEASONS, return_value=["2025-26"]),
            patch(_DISCOVERY, return_value=mock_discovery),
            patch(_REGISTRY),
            patch.object(orch, "_build_runner", return_value=mock_runner),
            patch.object(orch, "_transform_and_load", return_value=(0, 0, 0)),
            patch.object(orch, "_run_live_snapshot_upkeep", return_value=(0, 0)),
        ):
            result = asyncio.run(orch.run_monthly())

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
            season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        )
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = ["2026-02-28"]
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result(
                seasons=("2025-26",),
                season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
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
            patch.object(orch, "_run_live_snapshot_upkeep", return_value=(0, 0)),
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
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result()
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result()
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
        mock_runner.run_pattern.assert_awaited_once()
        assert mock_runner.run_pattern.await_args.args[0] == "season"
        assert mock_runner.run_pattern.await_args.args[1] == [{"season": "2024-25"}]

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
            _player_team_discovery_result()
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
            [("ep1", '{"season": "2024-25"}', "TimeoutError")],
            [],
        ]

        mock_discovery = AsyncMock()
        mock_discovery.discover_game_ids_result.return_value = _game_discovery_result()
        mock_discovery.discover_player_ids.return_value = []
        mock_discovery.discover_team_ids.return_value = []
        mock_discovery.discover_game_dates.return_value = []
        mock_discovery.discover_player_team_season_params_result.return_value = (
            _player_team_discovery_result()
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
            ("ep1", '{"season": "2024-25"}'),
        }
