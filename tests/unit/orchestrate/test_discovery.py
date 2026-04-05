"""Unit tests for nbadb.orchestrate.discovery module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from nbadb.orchestrate.discovery import (
    _CONCURRENT_DISCOVERY_TIMEOUT,
    EntityDiscovery,
    _extract_with_retry,
)


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    """Patch retry delay to 0 for fast tests."""
    monkeypatch.setattr("nbadb.orchestrate.discovery._RETRY_DELAY", 0.0)
    monkeypatch.setattr("nbadb.orchestrate.discovery.random.uniform", lambda *_args: 0.0)
    monkeypatch.setattr(
        "nbadb.orchestrate.discovery.get_settings",
        lambda: SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=2,
            extract_retry_base_delay=0.0,
        ),
    )


# ---------------------------------------------------------------------------
# _extract_with_retry
# ---------------------------------------------------------------------------


class TestExtractWithRetry:
    async def test_success_on_first_try(self):
        ext = MagicMock()
        df = pl.DataFrame({"a": [1]})
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            result = await _extract_with_retry(ext, "test")
        assert result.shape[0] == 1

    async def test_retries_on_failure_then_succeeds(self):
        ext = MagicMock()
        df = pl.DataFrame({"a": [1]})
        call_count = 0

        def _side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return df

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            result = await _extract_with_retry(ext, "test")
        assert result.shape[0] == 1
        assert call_count == 3

    async def test_raises_after_all_retries_exhausted(self):
        ext = MagicMock()
        with (
            patch(
                "nbadb.orchestrate.discovery._sync_extract",
                side_effect=ConnectionError("fail"),
            ),
            pytest.raises(ConnectionError, match="fail"),
        ):
            await _extract_with_retry(ext, "test")

    async def test_passes_kwargs_to_sync_extract(self):
        ext = MagicMock()
        df = pl.DataFrame({"x": [1]})
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df) as mock_se:
            await _extract_with_retry(ext, "test", season="2024-25", season_type="Playoffs")
        mock_se.assert_called_once_with(ext, season="2024-25", season_type="Playoffs")


# ---------------------------------------------------------------------------
# EntityDiscovery
# ---------------------------------------------------------------------------


class TestDiscoverGameDates:
    async def test_empty_dataframe(self):
        disc = EntityDiscovery(MagicMock())
        result = await disc.discover_game_dates(pl.DataFrame())
        assert result == []

    async def test_returns_sorted_unique_dates(self):
        disc = EntityDiscovery(MagicMock())
        df = pl.DataFrame({"game_date": ["2025-01-15", "2025-01-10", "2025-01-15"]})
        result = await disc.discover_game_dates(df)
        assert result == ["2025-01-10", "2025-01-15"]

    async def test_single_date(self):
        disc = EntityDiscovery(MagicMock())
        df = pl.DataFrame({"game_date": ["2025-03-01"]})
        result = await disc.discover_game_dates(df)
        assert result == ["2025-03-01"]


class TestDiscoverPlayerIds:
    async def test_filters_active_players(self):
        df = pl.DataFrame({"person_id": [1, 2, 3], "is_active": [1, 0, 1]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_ids(season="2024-25")
        assert result == [1, 3]

    async def test_filters_active_players_from_roster_status(self):
        df = pl.DataFrame({"person_id": [1, 2, 3], "roster_status": [1, 0, 1]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_ids(season="2024-25")
        assert result == [1, 3]

    async def test_returns_empty_on_failure(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=ConnectionError("fail"),
        ):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_ids()
        assert result == []

    async def test_no_is_active_column_returns_all(self):
        """When is_active column is missing, all players are returned."""
        df = pl.DataFrame({"person_id": [10, 20, 30]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_ids()
        assert result == [10, 20, 30]


class TestDiscoverAllPlayerIds:
    async def test_returns_all_players_unfiltered(self):
        df = pl.DataFrame({"person_id": [1, 2, 3], "is_active": [1, 0, 1]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            result = await disc.discover_all_player_ids(season="2024-25")
        assert result == [1, 2, 3]


class TestDiscoverPlayerTeamSeasonParams:
    async def test_returns_unique_player_team_season_params(self):
        season_frames = {
            "2024-25": pl.DataFrame(
                {
                    "person_id": [1, 2, 2, 3],
                    "team_id": [10, 20, 20, 0],
                }
            ),
            "2025-26": pl.DataFrame({"person_id": [4], "team_id": [30]}),
        }

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext

        def _by_season(*_args, **kwargs):
            return season_frames[kwargs["season"]]

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_by_season):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_team_season_params(["2024-25", "2025-26"])

        assert result == [
            {"player_id": 1, "team_id": 10, "season": "2024-25"},
            {"player_id": 2, "team_id": 20, "season": "2024-25"},
            {"player_id": 4, "team_id": 30, "season": "2025-26"},
        ]

    async def test_returns_empty_on_failure(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=ConnectionError("fail"),
        ):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_team_season_params(["2024-25"])
        assert result == []

    async def test_recovers_failed_seasons_sequentially(self):
        call_counts: dict[str, int] = {}

        def _side_effect(*_args, **kwargs):
            season = kwargs["season"]
            call_counts[season] = call_counts.get(season, 0) + 1
            if season == "2024-25" and call_counts[season] <= 3:
                raise ConnectionError("fail")
            return pl.DataFrame(
                {
                    "person_id": [1 if season == "2024-25" else 2],
                    "team_id": [10 if season == "2024-25" else 20],
                }
            )

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=2,
            extract_max_retries=2,
            extract_retry_base_delay=0.0,
        )
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg, settings=settings)
            result = await disc.discover_player_team_season_params(["2024-25", "2025-26"])

        assert result == [
            {"player_id": 1, "team_id": 10, "season": "2024-25"},
            {"player_id": 2, "team_id": 20, "season": "2025-26"},
        ]
        assert call_counts == {
            "2024-25": 4,
            "2025-26": 1,
        }

    @pytest.mark.parametrize(
        ("invalid_frames", "valid_frame"),
        [
            (
                [pl.DataFrame()],
                pl.DataFrame({"person_id": [1], "team_id": [10]}),
            ),
            (
                [pl.DataFrame({"person_id": [1]})],
                pl.DataFrame({"person_id": [1], "team_id": [10]}),
            ),
        ],
    )
    async def test_recovers_empty_or_malformed_seasons_sequentially(
        self,
        invalid_frames: list[pl.DataFrame],
        valid_frame: pl.DataFrame,
    ):
        season_frames = {
            "2024-25": [*invalid_frames, valid_frame],
            "2025-26": [pl.DataFrame({"person_id": [2], "team_id": [20]})],
        }
        call_counts: dict[str, int] = {}

        def _side_effect(*_args, **kwargs):
            season = kwargs["season"]
            call_counts[season] = call_counts.get(season, 0) + 1
            return season_frames[season].pop(0)

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_team_season_params(["2024-25", "2025-26"])

        assert result == [
            {"player_id": 1, "team_id": 10, "season": "2024-25"},
            {"player_id": 2, "team_id": 20, "season": "2025-26"},
        ]
        assert call_counts == {
            "2024-25": 2,
            "2025-26": 1,
        }

    async def test_defers_failed_seasons_to_recovery_before_full_budget(self):
        call_counts: dict[str, int] = {}

        def _side_effect(*_args, **kwargs):
            season = kwargs["season"]
            call_counts[season] = call_counts.get(season, 0) + 1
            if season == "2024-25" and call_counts[season] <= 2:
                raise ConnectionError("fail")
            return pl.DataFrame(
                {
                    "person_id": [1 if season == "2024-25" else 2],
                    "team_id": [10 if season == "2024-25" else 20],
                }
            )

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=2,
            extract_max_retries=4,
            extract_retry_base_delay=0.0,
        )
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg, settings=settings)
            result = await disc.discover_player_team_season_params(["2024-25", "2025-26"])

        assert result == [
            {"player_id": 1, "team_id": 10, "season": "2024-25"},
            {"player_id": 2, "team_id": 20, "season": "2025-26"},
        ]
        assert call_counts == {
            "2024-25": 3,
            "2025-26": 1,
        }

    async def test_uses_shorter_timeout_during_concurrent_season_sweep(self):
        call_kwargs: list[dict[str, object]] = []

        def _side_effect(*_args, **kwargs):
            call_kwargs.append(dict(kwargs))
            if len(call_kwargs) <= 2:
                raise ConnectionError("fail")
            return pl.DataFrame({"person_id": [1], "team_id": [10]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=4,
            extract_retry_base_delay=0.0,
        )
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg, settings=settings)
            result = await disc.discover_player_team_season_params(["2024-25"])

        assert result == [{"player_id": 1, "team_id": 10, "season": "2024-25"}]
        assert [kwargs.get("timeout") for kwargs in call_kwargs] == [
            _CONCURRENT_DISCOVERY_TIMEOUT,
            None,
            None,
        ]


class TestDiscoverTeamIds:
    async def test_returns_team_ids(self):
        df = pl.DataFrame({"team_id": [10, 20]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            result = await disc.discover_team_ids()
        assert result == [10, 20]

    async def test_empty_result(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            return_value=pl.DataFrame(),
        ):
            disc = EntityDiscovery(reg)
            result = await disc.discover_team_ids()
        assert result == []


class TestDiscoverGameIds:
    async def test_returns_unique_sorted_game_ids(self):
        df = pl.DataFrame({"game_id": ["001", "002", "001"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            ids, combined = await disc.discover_game_ids(["2024-25"])
        assert ids == ["001", "002"]
        assert combined.shape[0] == 3

    async def test_empty_result(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            return_value=pl.DataFrame(),
        ):
            disc = EntityDiscovery(reg)
            ids, combined = await disc.discover_game_ids(["2024-25"])
        assert ids == []
        assert combined.is_empty()

    async def test_multiple_seasons(self):
        call_count = 0

        def _make_df(*a, **kw):
            nonlocal call_count
            call_count += 1
            return pl.DataFrame({"game_id": [f"00{call_count}"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_make_df):
            disc = EntityDiscovery(reg)
            ids, combined = await disc.discover_game_ids(["2023-24", "2024-25"])
        assert len(ids) == 2
        assert combined.shape[0] == 2

    async def test_multiple_season_types(self):
        call_count = 0

        def _make_df(*a, **kw):
            nonlocal call_count
            call_count += 1
            return pl.DataFrame({"game_id": [f"00{call_count}"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_make_df):
            disc = EntityDiscovery(reg)
            ids, combined = await disc.discover_game_ids(
                ["2024-25"],
                season_types=["Regular Season", "Playoffs"],
            )
        assert len(ids) == 2
        assert call_count == 2

    async def test_uses_configured_retry_budget(self):
        call_count = 0

        def _side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 5:
                raise ConnectionError("fail")
            return pl.DataFrame({"game_id": ["001"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=4,
            extract_retry_base_delay=0.0,
        )
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg, settings=settings)
            ids, combined = await disc.discover_game_ids(["2024-25"])
        assert ids == ["001"]
        assert combined.shape[0] == 1
        assert call_count == 5

    async def test_recovers_failed_combos_sequentially(self):
        call_counts: dict[tuple[str, str], int] = {}

        def _side_effect(*_args, **kwargs):
            key = (kwargs["season"], kwargs["season_type"])
            call_counts[key] = call_counts.get(key, 0) + 1
            if key == ("2024-25", "Regular Season") and call_counts[key] <= 3:
                raise ConnectionError("fail")
            game_id = "001" if key[1] == "Regular Season" else "002"
            return pl.DataFrame({"game_id": [game_id]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        progress = MagicMock()
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg)
            ids, combined = await disc.discover_game_ids(
                ["2024-25"],
                on_progress=progress,
                season_types=["Regular Season", "Playoffs"],
            )

        assert ids == ["001", "002"]
        assert combined.shape[0] == 2
        assert call_counts == {
            ("2024-25", "Regular Season"): 4,
            ("2024-25", "Playoffs"): 1,
        }
        assert progress.start_pattern.call_args_list[0].args == ("game discovery (2 combos)", 2)
        assert progress.start_pattern.call_args_list[1].args == (
            "game discovery recovery (1 combos)",
            1,
        )

    async def test_defers_failed_combos_to_recovery_before_full_budget(self):
        call_counts: dict[tuple[str, str], int] = {}

        def _side_effect(*_args, **kwargs):
            key = (kwargs["season"], kwargs["season_type"])
            call_counts[key] = call_counts.get(key, 0) + 1
            if key == ("2024-25", "Regular Season") and call_counts[key] <= 2:
                raise ConnectionError("fail")
            game_id = "001" if key[1] == "Regular Season" else "002"
            return pl.DataFrame({"game_id": [game_id]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        progress = MagicMock()
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=2,
            extract_max_retries=4,
            extract_retry_base_delay=0.0,
        )
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg, settings=settings)
            ids, combined = await disc.discover_game_ids(
                ["2024-25"],
                on_progress=progress,
                season_types=["Regular Season", "Playoffs"],
            )

        assert ids == ["001", "002"]
        assert combined.shape[0] == 2
        assert call_counts == {
            ("2024-25", "Regular Season"): 3,
            ("2024-25", "Playoffs"): 1,
        }
        assert progress.start_pattern.call_args_list[1].args == (
            "game discovery recovery (1 combos)",
            1,
        )

    async def test_uses_shorter_timeout_during_concurrent_game_sweep(self):
        call_kwargs: list[dict[str, object]] = []

        def _side_effect(*_args, **kwargs):
            call_kwargs.append(dict(kwargs))
            if len(call_kwargs) <= 2:
                raise ConnectionError("fail")
            return pl.DataFrame({"game_id": ["001"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=4,
            extract_retry_base_delay=0.0,
        )
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg, settings=settings)
            ids, combined = await disc.discover_game_ids(
                ["2024-25"],
                season_types=["Regular Season"],
            )

        assert ids == ["001"]
        assert combined.shape[0] == 1
        assert [kwargs.get("timeout") for kwargs in call_kwargs] == [
            _CONCURRENT_DISCOVERY_TIMEOUT,
            None,
            None,
        ]

    async def test_failure_in_one_season_does_not_cancel_others(self):
        call_count = 0

        def _side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("fail")
            return pl.DataFrame({"game_id": ["002"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg)
            ids, combined = await disc.discover_game_ids(["2023-24", "2024-25"])
        # One season failed, but the other should still work
        assert "002" in ids

    async def test_on_progress_callback(self):
        df = pl.DataFrame({"game_id": ["001"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        progress = MagicMock()
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            await disc.discover_game_ids(["2024-25"], on_progress=progress)
        progress.start_pattern.assert_called_once()
        progress.advance_pattern.assert_called_once_with(success=True)
