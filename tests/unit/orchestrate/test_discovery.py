"""Unit tests for nbadb.orchestrate.discovery module."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from threading import Barrier, Event, Lock
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from nbadb.core.errors import (
    ExtractionError,
    ParserInputCaptureIntegrityError,
    TransientError,
    ValidationError,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.types import PLAY_IN_UPSTREAM_UNAVAILABLE_REASON, SeasonType
from nbadb.extract.bronze import ParserInputContext, canonical_parameters_sha256
from nbadb.extract.nba_api_adapter import NbaApiCaptureContract

if TYPE_CHECKING:
    from nbadb.core.config import NbaDbSettings
    from nbadb.extract.bronze import ParserInputCaptureSink

from nbadb.orchestrate.discovery import (
    _BROAD_OUTAGE_CANARY_ATTEMPTS_CAP,
    _CONCURRENT_DISCOVERY_TIMEOUT,
    _RECOVERY_DISCOVERY_TIMEOUT,
    DiscoveryCaptureCompletion,
    DiscoveryCaptureScopeKey,
    EntityDiscovery,
    GameDiscoveryResult,
    PlayerIdDiscoveryResult,
    PlayerTeamSeasonDiscoveryResult,
    _extract_with_retry,
)


def _as_settings(value: object) -> NbaDbSettings:
    """Type a deliberately minimal settings double at the constructor boundary."""

    return cast("NbaDbSettings", value)


class _DiscoveryCaptureSink:
    def __init__(self) -> None:
        self.logical_calls: list[dict[str, object]] = []

    def record_logical_call(self, **kwargs: object) -> str:
        self.logical_calls.append(dict(kwargs))
        payload = repr((len(self.logical_calls), sorted(kwargs.items()))).encode()
        return hashlib.sha256(payload).hexdigest()


class _CaptureAwareExtractor:
    def __init__(self) -> None:
        self.capture_contract: NbaApiCaptureContract | None = None

    def set_capture_contract(self, contract: NbaApiCaptureContract | None) -> None:
        self.capture_contract = contract

    def capture_receipt_snapshot(self):
        assert self.capture_contract is not None
        return self.capture_contract.receipt_snapshot()


class _DiscoveryCaptureHarness:
    def __init__(self) -> None:
        self.sink = _DiscoveryCaptureSink()
        self.factory_calls: list[tuple[str, dict[str, object]]] = []
        self.contracts: list[NbaApiCaptureContract] = []
        self.completions: list[DiscoveryCaptureCompletion] = []

    def contract_for(
        self,
        endpoint_name: str,
        params: dict[str, object],
    ) -> NbaApiCaptureContract:
        self.factory_calls.append((endpoint_name, dict(params)))
        contract = NbaApiCaptureContract(
            sink=cast("ParserInputCaptureSink", self.sink),
            context=ParserInputContext(
                attempt_id=f"discovery-call-{len(self.contracts):04d}",
            ),
            provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
            endpoint_contract_sha256="b" * 64,
        )
        self.contracts.append(contract)
        return contract

    def complete(self, completion: DiscoveryCaptureCompletion) -> None:
        self.completions.append(completion)


def _record_capture_attempt(
    extractor: _CaptureAwareExtractor,
    *,
    successful: bool,
) -> ParserInputContext:
    contract = extractor.capture_contract
    assert contract is not None
    context = contract.begin_request()
    receipt = hashlib.sha256(
        f"{context.attempt_id}:{context.retry_ordinal}:{context.request_ordinal}".encode()
    ).hexdigest()
    contract.record_receipt(context, receipt, successful=successful)
    return context


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
    def test_retries_transient_error_then_succeeds_without_async_plugin(self):
        ext = MagicMock()
        df = pl.DataFrame({"a": [1]})
        call_count = 0

        def _side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TransientError("retry me")
            return df

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            result = asyncio.run(_extract_with_retry(ext, "test"))

        assert result.shape[0] == 1
        assert call_count == 3

    def test_does_not_retry_non_retryable_extraction_error_without_async_plugin(self):
        ext = MagicMock()

        with (
            patch(
                "nbadb.orchestrate.discovery._sync_extract",
                side_effect=ExtractionError("boom"),
            ) as mock_sync_extract,
            pytest.raises(ExtractionError, match="boom"),
        ):
            asyncio.run(_extract_with_retry(ext, "test"))

        assert mock_sync_extract.call_count == 1

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

    async def test_retries_validation_response_then_succeeds(self):
        ext = MagicMock()
        df = pl.DataFrame({"a": [1]})

        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=[ValidationError("invalid response"), df],
        ) as sync_extract:
            result = await _extract_with_retry(ext, "test")

        assert result.equals(df)
        assert sync_extract.call_count == 2

    async def test_retries_wrapped_transport_error_then_succeeds(self):
        ext = MagicMock()
        df = pl.DataFrame({"a": [1]})
        call_count = 0

        def _wrapped_transport(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                try:
                    raise TimeoutError
                except TimeoutError as exc:
                    raise ExtractionError("wrapped transport") from exc
            return df

        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=_wrapped_transport,
        ) as sync_extract:
            result = await _extract_with_retry(ext, "test")

        assert result.equals(df)
        assert sync_extract.call_count == 2

    @pytest.mark.parametrize(
        "root_error",
        [json.JSONDecodeError("invalid", "", 0), KeyError("missing")],
    )
    async def test_retries_wrapped_response_contract_then_succeeds(self, root_error):
        ext = MagicMock()
        df = pl.DataFrame({"a": [1]})
        call_count = 0

        def _wrapped_response(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ExtractionError("wrapped response") from root_error
            return df

        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=_wrapped_response,
        ) as sync_extract:
            result = await _extract_with_retry(ext, "test")

        assert result.equals(df)
        assert sync_extract.call_count == 2

    async def test_raises_after_all_retries_exhausted(self):
        ext = MagicMock()
        with (
            patch(
                "nbadb.orchestrate.discovery._sync_extract",
                side_effect=ConnectionError("fail"),
            ),
            pytest.raises(TransientError, match="test: transient extraction failure"),
        ):
            await _extract_with_retry(ext, "test")

    async def test_passes_kwargs_to_sync_extract(self):
        ext = MagicMock()
        df = pl.DataFrame({"x": [1]})
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df) as mock_se:
            await _extract_with_retry(ext, "test", season="2024-25", season_type="Playoffs")
        mock_se.assert_called_once_with(
            ext,
            season="2024-25",
            season_type="Playoffs",
            timeout=_RECOVERY_DISCOVERY_TIMEOUT,
        )

    async def test_replaces_unbounded_timeout_and_sets_extractor_backstop(self):
        class _Ext:
            _request_timeout_override: int | None = None

        ext = _Ext()
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            return_value=pl.DataFrame({"x": [1]}),
        ) as mock_sync_extract:
            await _extract_with_retry(ext, "test", timeout=None)

        mock_sync_extract.assert_called_once_with(ext, timeout=_RECOVERY_DISCOVERY_TIMEOUT)
        assert ext._request_timeout_override == int(_RECOVERY_DISCOVERY_TIMEOUT[-1])


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
    async def test_returns_all_players_unfiltered_without_season(self):
        df = pl.DataFrame({"person_id": [1, 2, 3], "is_active": [1, 0, 1]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            result = await disc.discover_all_player_ids()
        assert result == [1, 2, 3]

    async def test_filters_all_players_to_requested_season_window(self):
        df = pl.DataFrame(
            {
                "person_id": [1, 2, 3, 4],
                "from_year": ["1945", "1946", "1947", None],
                "to_year": ["1945", "1946", "1950", None],
            }
        )

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df) as sync_extract:
            disc = EntityDiscovery(reg)
            result = await disc.discover_all_player_ids(season="1946-47")
        assert result == [2]
        sync_extract.assert_called_once()
        assert sync_extract.call_args.kwargs == {
            "allow_static_fallback": False,
            "timeout": _CONCURRENT_DISCOVERY_TIMEOUT,
        }

    @pytest.mark.parametrize(
        ("responses", "expected_failure", "expected_sources"),
        [
            (
                [ConnectionError("common"), ConnectionError("index")],
                "transport",
                {"common_all_players": "transport", "player_index": "transport"},
            ),
            (
                [
                    pl.DataFrame({"person_id": [1]}),
                    pl.DataFrame({"person_id": [1]}),
                ],
                "response",
                {"common_all_players": "response", "player_index": "response"},
            ),
            (
                [ExtractionError("common"), ExtractionError("index")],
                "permanent",
                {"common_all_players": "permanent", "player_index": "permanent"},
            ),
            (
                [
                    pl.DataFrame(
                        schema={
                            "person_id": pl.Int64,
                            "from_year": pl.String,
                            "to_year": pl.String,
                        }
                    )
                ],
                "no_data",
                {"common_all_players": "no_data"},
            ),
        ],
    )
    async def test_result_exposes_structured_player_discovery_failure_taxonomy(
        self,
        responses: list[object],
        expected_failure: str,
        expected_sources: dict[str, str],
    ):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=0,
            extract_retry_base_delay=0.0,
        )
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=responses,
        ) as sync_extract:
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_all_player_ids_result(season="1946-47")

        assert isinstance(result, PlayerIdDiscoveryResult)
        assert result.ids == []
        assert result.is_complete is False
        assert result.failure_kind == expected_failure
        assert result.failures_by_source == expected_sources
        assert sync_extract.call_count == len(responses)

    async def test_season_filter_uses_player_index_when_common_year_metadata_is_unusable(self):
        common_df = pl.DataFrame(
            {
                "person_id": [1, 2, 3],
                "from_year": [None, None, None],
                "to_year": [None, None, None],
            }
        )
        player_index_df = pl.DataFrame(
            {
                "person_id": [1, 2, 3],
                "from_year": ["1945", "1946", "1947"],
                "to_year": ["1945", "1946", "1950"],
            }
        )

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.side_effect = [_Ext, _Ext]
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=[common_df, player_index_df],
        ) as sync_extract:
            disc = EntityDiscovery(reg)
            result = await disc.discover_all_player_ids(season="1946-47")
        assert result == [2]
        assert [call.kwargs for call in sync_extract.call_args_list] == [
            {
                "allow_static_fallback": False,
                "timeout": _CONCURRENT_DISCOVERY_TIMEOUT,
            },
            {"season": "1946-47", "timeout": _CONCURRENT_DISCOVERY_TIMEOUT},
        ]

    async def test_season_filter_returns_empty_when_no_source_has_usable_year_metadata(self):
        df = pl.DataFrame(
            {
                "person_id": [1, 2, 3],
                "from_year": [None, None, None],
                "to_year": [None, None, None],
            }
        )

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.side_effect = [_Ext, _Ext]
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=[df, df]):
            disc = EntityDiscovery(reg)
            result = await disc.discover_all_player_ids(season="1946-47")
        assert result == []

    async def test_bulk_season_filter_maps_all_players_to_requested_seasons(self):
        df = pl.DataFrame(
            {
                "person_id": [1, 2, 3, 4],
                "from_year": ["1945", "1946", "1947", "1964"],
                "to_year": ["1945", "1946", "1950", "1965"],
            }
        )

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df) as sync_extract:
            disc = EntityDiscovery(reg)
            result = await disc.discover_all_player_ids_by_season(
                ["1946-47", "1947-48", "1964-65", "1946-47"]
            )

        assert result == {
            "1946-47": [2],
            "1947-48": [3],
            "1964-65": [4],
        }
        sync_extract.assert_called_once()
        assert sync_extract.call_args.kwargs == {
            "allow_static_fallback": False,
            "timeout": _CONCURRENT_DISCOVERY_TIMEOUT,
        }

    async def test_bulk_season_filter_omits_seasons_when_year_metadata_is_unusable(self):
        df = pl.DataFrame(
            {
                "person_id": [1, 2, 3],
                "from_year": [None, None, None],
                "to_year": [None, None, None],
            }
        )

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            result = await disc.discover_all_player_ids_by_season(["1946-47"])

        assert result == {}


class TestDiscoverPlayerTeamSeasonParams:
    async def test_returns_unique_player_team_season_params(self):
        season_frames = {
            "2024-25": pl.DataFrame(
                {
                    "player_id": [1, 2, 2, 2, 3],
                    "team_id": [10, 20, 20, 21, 0],
                }
            ),
            "2025-26": pl.DataFrame({"player_id": [4], "team_id": [30]}),
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
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 2,
                "team_id": 21,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 4,
                "team_id": 30,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
        ]
        reg.get.assert_called_once_with("player_game_logs")

    async def test_classifies_pre_play_in_scope_without_requesting_it(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        calls: list[tuple[str, str]] = []

        def _side_effect(*_args, **kwargs):
            calls.append((kwargs["season"], kwargs["season_type"]))
            return pl.DataFrame({"player_id": [1], "team_id": [10]})

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            result = await EntityDiscovery(reg).discover_player_team_season_params_result(
                ["2018-19", "2019-20"],
                season_types=[SeasonType.PLAY_IN.value],
            )

        assert calls == [("2019-20", SeasonType.PLAY_IN.value)]
        assert result.covered_pairs == result.requested_pairs
        assert result.upstream_unavailable_pairs == {
            ("2018-19", SeasonType.PLAY_IN.value): PLAY_IN_UPSTREAM_UNAVAILABLE_REASON
        }
        assert result.params == [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2019-20",
                "season_type": SeasonType.PLAY_IN.value,
            }
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

    async def test_result_treats_typed_empty_workload_scope_as_covered(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext

        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            return_value=pl.DataFrame(schema={"player_id": pl.Int64, "team_id": pl.Int64}),
        ):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_team_season_params_result(
                ["2024-25"],
                season_types=["Regular Season", "Playoffs"],
            )

        assert result.params == []
        assert result.covered_pairs == {
            ("2024-25", "Regular Season"),
            ("2024-25", "Playoffs"),
        }
        assert result.is_complete is True

    async def test_result_treats_filtered_empty_player_discovery_as_uncovered(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext

        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            return_value=pl.DataFrame({"player_id": [1], "team_id": [0]}),
        ):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_team_season_params_result(
                ["2024-25"],
                season_types=["Regular Season", "Playoffs"],
            )

        assert result.params == []
        assert result.covered_pairs == frozenset()
        assert result.is_complete is False

    async def test_result_tracks_only_successfully_covered_seasons(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext

        def _side_effect(*_args, **kwargs):
            if kwargs["season"] == "2025-26":
                raise ConnectionError("fail")
            return pl.DataFrame({"player_id": [1], "team_id": [10]})

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_team_season_params_result(
                ["2024-25", "2025-26"],
                season_types=["Regular Season", "Playoffs"],
            )

        assert isinstance(result, PlayerTeamSeasonDiscoveryResult)
        assert result.covered_pairs == {
            ("2024-25", "Regular Season"),
            ("2024-25", "Playoffs"),
        }
        assert result.requested_pairs == {
            ("2024-25", "Regular Season"),
            ("2024-25", "Playoffs"),
            ("2025-26", "Regular Season"),
            ("2025-26", "Playoffs"),
        }
        assert result.is_complete is False

    async def test_recovers_failed_seasons_sequentially(self):
        call_counts: dict[str, int] = {}

        def _side_effect(*_args, **kwargs):
            season = kwargs["season"]
            call_counts[season] = call_counts.get(season, 0) + 1
            if season == "2024-25" and call_counts[season] <= 2:
                raise ConnectionError("fail")
            return pl.DataFrame(
                {
                    "player_id": [1 if season == "2024-25" else 2],
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
        with (
            patch("nba_api.stats.library.http.NBAStatsHTTP.set_session") as set_session,
            patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect),
        ):
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_player_team_season_params(["2024-25", "2025-26"])

        assert result == [
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
        assert call_counts == {
            "2024-25": 3,
            "2025-26": 1,
        }
        set_session.assert_not_called()

    async def test_recovers_malformed_seasons_sequentially(
        self,
    ):
        season_frames = {
            "2024-25": [
                pl.DataFrame({"player_id": [1]}),
                pl.DataFrame({"player_id": [1], "team_id": [10]}),
            ],
            "2025-26": [pl.DataFrame({"player_id": [2], "team_id": [20]})],
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
                    "player_id": [1 if season == "2024-25" else 2],
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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_player_team_season_params(["2024-25", "2025-26"])

        assert result == [
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
        assert call_counts == {
            "2024-25": 3,
            "2025-26": 1,
        }

    async def test_keeps_total_call_budget_across_player_team_recovery(self):
        call_counts: dict[str, int] = {}

        def _side_effect(*_args, **kwargs):
            season = kwargs["season"]
            call_counts[season] = call_counts.get(season, 0) + 1
            if season == "2024-25" and call_counts[season] <= 3:
                raise ConnectionError("fail")
            return pl.DataFrame(
                {
                    "player_id": [1 if season == "2024-25" else 2],
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
        with (
            patch("nba_api.stats.library.http.NBAStatsHTTP.set_session") as set_session,
            patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect),
        ):
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_player_team_season_params(["2024-25", "2025-26"])

        assert result == [
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2025-26",
                "season_type": "Regular Season",
            },
        ]
        assert call_counts == {
            "2024-25": 3,
            "2025-26": 1,
        }
        set_session.assert_not_called()

    async def test_broad_transport_outage_uses_bounded_canary_and_honors_concurrency(self):
        seasons = ["2021-22", "2022-23", "2023-24", "2024-25"]
        barrier = Barrier(2)
        lock = Lock()
        calls: list[str] = []
        active = 0
        max_active = 0

        def _side_effect(*_args, **kwargs):
            nonlocal active, max_active
            season = kwargs["season"]
            with lock:
                calls.append(season)
                is_fast_pass = len(calls) <= len(seasons) * 2
                active += 1
                max_active = max(max_active, active)
            try:
                if is_fast_pass:
                    barrier.wait(timeout=5)
                raise ConnectionError("broad outage")
            finally:
                with lock:
                    active -= 1

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
        with (
            patch("nba_api.stats.library.http.NBAStatsHTTP.set_session") as set_session,
            patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect),
        ):
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_player_team_season_params_result(
                seasons,
                season_types=["Regular Season", "Playoffs"],
            )

        assert result.requested_pairs == {
            (season, season_type)
            for season in seasons
            for season_type in ["Regular Season", "Playoffs"]
        }
        assert result.covered_pairs == frozenset()
        assert Counter(calls) == Counter(
            {
                "2021-22": 2 + _BROAD_OUTAGE_CANARY_ATTEMPTS_CAP,
                "2022-23": 2,
                "2023-24": 2,
                "2024-25": 2,
            }
        )
        assert result.failures_by_pair == {
            (season, season_type): "transport"
            for season in seasons
            for season_type in ["Regular Season", "Playoffs"]
        }
        assert max_active == 2
        set_session.assert_not_called()

    async def test_broad_response_outage_uses_bounded_canary_without_serial_fanout(self):
        seasons = ["2021-22", "2022-23", "2023-24", "2024-25"]
        calls: list[str] = []

        def _side_effect(*_args, **kwargs):
            calls.append(kwargs["season"])
            return pl.DataFrame({"player_id": [1]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_player_team_season_params_result(seasons)

        assert Counter(calls) == Counter(
            {
                "2021-22": 1 + _BROAD_OUTAGE_CANARY_ATTEMPTS_CAP,
                "2022-23": 1,
                "2023-24": 1,
                "2024-25": 1,
            }
        )
        assert result.covered_pairs == frozenset()
        assert result.failures_by_pair == {
            (season, "Regular Season"): "response" for season in seasons
        }

    async def test_mixed_broad_player_team_outage_isolates_failure_class_canaries(self):
        seasons = ["2021-22", "2022-23", "2023-24", "2024-25"]
        calls: Counter[str] = Counter()
        response_seasons = {"2021-22", "2023-24"}
        transport_seasons = {"2022-23", "2024-25"}

        def _side_effect(*_args, **kwargs):
            season = kwargs["season"]
            calls[season] += 1
            if season in response_seasons:
                return pl.DataFrame({"player_id": [1]})
            if calls[season] == 1:
                raise ConnectionError("transport outage")
            return pl.DataFrame({"player_id": [1], "team_id": [10]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_player_team_season_params_result(seasons)

        assert calls == Counter(
            {
                "2021-22": 1 + _BROAD_OUTAGE_CANARY_ATTEMPTS_CAP,
                "2022-23": 2,
                "2023-24": 1,
                "2024-25": 2,
            }
        )
        assert result.covered_pairs == {(season, "Regular Season") for season in transport_seasons}
        assert result.failures_by_pair == {
            (season, "Regular Season"): "response" for season in response_seasons
        }

    async def test_does_not_recover_permanent_player_team_failures(self):
        seasons = ["2023-24", "2024-25"]

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
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=ExtractionError("permanent"),
        ) as sync_extract:
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_player_team_season_params_result(seasons)

        assert result.requested_pairs == {
            ("2023-24", "Regular Season"),
            ("2024-25", "Regular Season"),
        }
        assert result.covered_pairs == frozenset()
        assert result.failures_by_pair == {
            (season, "Regular Season"): "permanent" for season in seasons
        }
        assert sync_extract.call_count == len(seasons)

    async def test_player_team_response_shape_failures_use_exact_attempt_budget(self):
        call_kwargs: list[dict[str, object]] = []

        def _side_effect(*_args, **kwargs):
            call_kwargs.append(dict(kwargs))
            return pl.DataFrame({"player_id": [1]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=2,
            extract_retry_base_delay=0.0,
        )
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_player_team_season_params_result(["2024-25"])

        assert result.requested_pairs == {("2024-25", "Regular Season")}
        assert result.covered_pairs == frozenset()
        assert len(call_kwargs) == settings.extract_max_retries + 1
        assert [kwargs.get("timeout") for kwargs in call_kwargs] == [
            _CONCURRENT_DISCOVERY_TIMEOUT,
            _RECOVERY_DISCOVERY_TIMEOUT,
            _RECOVERY_DISCOVERY_TIMEOUT,
        ]
        assert result.failures_by_pair == {("2024-25", "Regular Season"): "response"}

    async def test_player_team_recovery_retries_validation_after_transport(self):
        season = "2010-11"
        recovered = pl.DataFrame({"player_id": [1], "team_id": [10]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=2,
            extract_retry_base_delay=0.0,
        )
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=[
                ConnectionError("transport"),
                ValidationError("invalid response"),
                recovered,
            ],
        ) as sync_extract:
            result = await EntityDiscovery(
                reg,
                settings=_as_settings(settings),
            ).discover_player_team_season_params_result([season])

        assert result.covered_pairs == {(season, "Regular Season")}
        assert result.failures_by_pair == {}
        assert result.params == [
            {
                "player_id": 1,
                "team_id": 10,
                "season": season,
                "season_type": "Regular Season",
            }
        ]
        assert sync_extract.call_count == settings.extract_max_retries + 1

    async def test_player_team_exhausts_wrapped_response_contract_budget(self):
        season = "2010-11"

        class _Ext:
            pass

        def _wrapped_response(*_args, **_kwargs):
            try:
                raise json.JSONDecodeError("invalid", "", 0)
            except json.JSONDecodeError as exc:
                raise ExtractionError("wrapped response") from exc

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=2,
            extract_retry_base_delay=0.0,
        )
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=_wrapped_response,
        ) as sync_extract:
            result = await EntityDiscovery(
                reg,
                settings=_as_settings(settings),
            ).discover_player_team_season_params_result([season])

        assert result.covered_pairs == frozenset()
        assert result.failures_by_pair == {(season, "Regular Season"): "response"}
        assert sync_extract.call_count == settings.extract_max_retries + 1

    async def test_uses_shorter_timeout_during_concurrent_season_sweep(self):
        call_kwargs: list[dict[str, object]] = []

        def _side_effect(*_args, **kwargs):
            call_kwargs.append(dict(kwargs))
            if len(call_kwargs) <= 2:
                raise ConnectionError("fail")
            return pl.DataFrame({"player_id": [1], "team_id": [10]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_player_team_season_params(["2024-25"])

        assert result == [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            }
        ]
        assert [kwargs.get("timeout") for kwargs in call_kwargs] == [
            _CONCURRENT_DISCOVERY_TIMEOUT,
            _RECOVERY_DISCOVERY_TIMEOUT,
            _RECOVERY_DISCOVERY_TIMEOUT,
        ]

    async def test_expands_player_team_season_params_across_requested_season_types(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            return_value=pl.DataFrame({"player_id": [1], "team_id": [10]}),
        ):
            disc = EntityDiscovery(reg)
            result = await disc.discover_player_team_season_params(
                ["2024-25"],
                season_types=["Regular Season", "Playoffs"],
            )

        assert result == [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Playoffs",
            },
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

    async def test_returns_current_nba_team_ids(self):
        df = pl.DataFrame(
            {
                "league_id": ["00", "00", "10", "00"],
                "team_id": [10, 20, 30, 40],
                "max_year": ["2024", "2025", "2025", "2025"],
            }
        )

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=df):
            disc = EntityDiscovery(reg)
            result = await disc.discover_current_team_ids()
        assert result == [20, 40]


class TestDiscoverGameIds:
    async def test_classifies_pre_play_in_scope_as_typed_zero_without_request(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        covered = MagicMock()
        calls: list[tuple[str, str]] = []

        def _side_effect(*_args, **kwargs):
            calls.append((kwargs["season"], kwargs["season_type"]))
            return pl.DataFrame({"game_id": ["0051900001"], "game_date": ["2020-08-15"]})

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            result = await EntityDiscovery(reg).discover_game_ids_result(
                ["2018-19", "2019-20"],
                season_types=[SeasonType.PLAY_IN.value],
                on_combo_covered=covered,
            )

        unavailable = ("2018-19", SeasonType.PLAY_IN.value)
        assert calls == [("2019-20", SeasonType.PLAY_IN.value)]
        assert result.covered_combos == result.requested_combos
        assert result.upstream_unavailable_combos == {
            unavailable: PLAY_IN_UPSTREAM_UNAVAILABLE_REASON
        }
        assert result.frames_by_combo[unavailable].schema == {
            "game_id": pl.String,
            "game_date": pl.String,
        }
        assert result.frames_by_combo[unavailable].is_empty()
        assert covered.call_count == 2

    async def test_returns_unique_sorted_game_ids(self):
        df = pl.DataFrame(
            {
                "game_id": ["001", "002", "001"],
                "game_date": ["2025-01-01", "2025-01-02", "2025-01-01"],
            }
        )

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

    async def test_result_marks_partial_combo_coverage_when_one_combo_fails(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext

        def _side_effect(*_args, **kwargs):
            combo = (kwargs["season"], kwargs["season_type"])
            if combo == ("2025-26", "Playoffs"):
                raise ConnectionError("fail")
            return pl.DataFrame(
                {
                    "game_id": [f"{kwargs['season']}-{kwargs['season_type']}"],
                    "game_date": ["2025-01-01"],
                }
            )

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg)
            result = await disc.discover_game_ids_result(
                ["2024-25", "2025-26"],
                season_types=["Regular Season", "Playoffs"],
            )

        assert isinstance(result, GameDiscoveryResult)
        assert ("2025-26", "Playoffs") in result.requested_combos
        assert ("2025-26", "Playoffs") not in result.covered_combos
        assert result.is_complete is False

    async def test_result_marks_empty_successful_combos_as_covered(self):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext

        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            return_value=pl.DataFrame(schema={"game_id": pl.String, "game_date": pl.String}),
        ):
            disc = EntityDiscovery(reg)
            result = await disc.discover_game_ids_result(
                ["2024-25"],
                season_types=["Regular Season", "Playoffs"],
            )

        assert result.game_ids == []
        assert result.raw.is_empty()
        assert result.covered_combos == {
            ("2024-25", "Regular Season"),
            ("2024-25", "Playoffs"),
        }
        assert result.is_complete is True

    @pytest.mark.parametrize(
        "frame",
        [
            pl.DataFrame({"game_id": ["001"]}),
            pl.DataFrame(
                {"game_id": [None], "game_date": ["2025-01-01"]},
                schema_overrides={"game_id": pl.String},
            ),
            pl.DataFrame({"game_id": ["  "], "game_date": ["2025-01-01"]}),
            pl.DataFrame(
                {"game_id": ["001"], "game_date": [None]},
                schema_overrides={"game_date": pl.String},
            ),
            pl.DataFrame({"game_id": ["001"], "game_date": ["  "]}),
            pl.DataFrame({"game_id": [1], "game_date": ["2025-01-01"]}),
            pl.DataFrame({"game_id": ["001"], "game_date": [1]}),
        ],
        ids=[
            "missing-game-date",
            "null-game-id",
            "blank-game-id",
            "null-game-date",
            "blank-game-date",
            "non-string-game-id",
            "invalid-game-date-type",
        ],
    )
    async def test_rejects_semantically_invalid_game_frames(self, frame: pl.DataFrame):
        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        with patch("nbadb.orchestrate.discovery._sync_extract", return_value=frame):
            disc = EntityDiscovery(reg)
            result = await disc.discover_game_ids_result(["2024-25"])

        assert result.covered_combos == frozenset()
        assert result.failures_by_combo == {("2024-25", "Regular Season"): "response"}

    async def test_multiple_seasons(self):
        call_count = 0

        def _make_df(*a, **kw):
            nonlocal call_count
            call_count += 1
            return pl.DataFrame({"game_id": [f"00{call_count}"], "game_date": ["2025-01-01"]})

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
            return pl.DataFrame({"game_id": [f"00{call_count}"], "game_date": ["2025-01-01"]})

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
            return pl.DataFrame({"game_id": ["001"], "game_date": ["2025-01-01"]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            ids, combined = await disc.discover_game_ids(["2024-25"])
        assert ids == ["001"]
        assert combined.shape[0] == 1
        assert call_count == 5

    async def test_recovers_failed_combos_sequentially(self):
        call_counts: dict[tuple[str, str], int] = {}

        def _side_effect(*_args, **kwargs):
            key = (kwargs["season"], kwargs["season_type"])
            call_counts[key] = call_counts.get(key, 0) + 1
            if key == ("2024-25", "Regular Season") and call_counts[key] <= 2:
                raise ConnectionError("fail")
            game_id = "001" if key[1] == "Regular Season" else "002"
            return pl.DataFrame({"game_id": [game_id], "game_date": ["2025-01-01"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        progress = MagicMock()
        with (
            patch("nba_api.stats.library.http.NBAStatsHTTP.set_session") as set_session,
            patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect),
        ):
            disc = EntityDiscovery(reg)
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
        assert progress.start_pattern.call_args_list[0].args == ("game discovery (2 combos)", 2)
        assert progress.start_pattern.call_args_list[1].args == (
            "game discovery recovery (1 combos)",
            1,
        )
        set_session.assert_not_called()

    async def test_defers_failed_combos_to_recovery_before_full_budget(self):
        call_counts: dict[tuple[str, str], int] = {}

        def _side_effect(*_args, **kwargs):
            key = (kwargs["season"], kwargs["season_type"])
            call_counts[key] = call_counts.get(key, 0) + 1
            if key == ("2024-25", "Regular Season") and call_counts[key] <= 2:
                raise ConnectionError("fail")
            game_id = "001" if key[1] == "Regular Season" else "002"
            return pl.DataFrame({"game_id": [game_id], "game_date": ["2025-01-01"]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
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

    async def test_keeps_total_call_budget_across_game_recovery(self):
        call_counts: dict[tuple[str, str], int] = {}

        def _side_effect(*_args, **kwargs):
            key = (kwargs["season"], kwargs["season_type"])
            call_counts[key] = call_counts.get(key, 0) + 1
            if key == ("2024-25", "Regular Season") and call_counts[key] <= 3:
                raise ConnectionError("fail")
            game_id = "001" if key[1] == "Regular Season" else "002"
            return pl.DataFrame({"game_id": [game_id], "game_date": ["2025-01-01"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        progress = MagicMock()
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=2,
            extract_max_retries=2,
            extract_retry_base_delay=0.0,
        )
        with (
            patch("nba_api.stats.library.http.NBAStatsHTTP.set_session") as set_session,
            patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect),
        ):
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            ids, combined = await disc.discover_game_ids(
                ["2024-25"],
                on_progress=progress,
                season_types=["Regular Season", "Playoffs"],
            )

        assert ids == ["002"]
        assert combined.shape[0] == 1
        assert call_counts == {
            ("2024-25", "Regular Season"): 3,
            ("2024-25", "Playoffs"): 1,
        }
        assert progress.start_pattern.call_args_list[1].args == (
            "game discovery recovery (1 combos)",
            1,
        )
        set_session.assert_not_called()

    async def test_exhausted_game_recovery_keeps_exact_partial_coverage(self):
        call_counts: dict[tuple[str, str], int] = {}

        def _side_effect(*_args, **kwargs):
            key = (kwargs["season"], kwargs["season_type"])
            call_counts[key] = call_counts.get(key, 0) + 1
            if key == ("2024-25", "Regular Season"):
                raise ConnectionError("fail")
            return pl.DataFrame({"game_id": ["002"], "game_date": ["2025-01-01"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        progress = MagicMock()
        covered_callbacks: list[tuple[tuple[str, str], list[str]]] = []
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=2,
            extract_max_retries=2,
            extract_retry_base_delay=0.0,
        )
        with (
            patch("nba_api.stats.library.http.NBAStatsHTTP.set_session") as set_session,
            patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect),
        ):
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_game_ids_result(
                ["2024-25"],
                on_progress=progress,
                season_types=["Regular Season", "Playoffs"],
                on_combo_covered=lambda combo, frame: covered_callbacks.append(
                    (combo, frame.get_column("game_id").to_list())
                ),
            )

        assert result.game_ids == ["002"]
        assert result.raw.shape[0] == 1
        assert result.requested_combos == {
            ("2024-25", "Regular Season"),
            ("2024-25", "Playoffs"),
        }
        assert result.covered_combos == {("2024-25", "Playoffs")}
        assert covered_callbacks == [(("2024-25", "Playoffs"), ["002"])]
        assert call_counts == {
            ("2024-25", "Regular Season"): 3,
            ("2024-25", "Playoffs"): 1,
        }
        assert progress.start_pattern.call_args_list[1].args == (
            "game discovery recovery (1 combos)",
            1,
        )
        set_session.assert_not_called()

    async def test_game_combo_callback_persists_before_other_fast_pass_tasks_finish(self):
        release_regular_season = Event()
        covered_callbacks: list[tuple[str, str]] = []

        def _side_effect(*_args, **kwargs):
            if kwargs["season_type"] == "Regular Season":
                assert release_regular_season.wait(timeout=5)
            game_id = "001" if kwargs["season_type"] == "Regular Season" else "002"
            return pl.DataFrame({"game_id": [game_id], "game_date": ["2025-01-01"]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            task = asyncio.create_task(
                disc.discover_game_ids_result(
                    ["2024-25"],
                    season_types=["Regular Season", "Playoffs"],
                    on_combo_covered=lambda combo, _frame: covered_callbacks.append(combo),
                )
            )
            for _attempt in range(100):
                if covered_callbacks:
                    break
                await asyncio.sleep(0.01)

            assert covered_callbacks == [("2024-25", "Playoffs")]
            assert not task.done()
            release_regular_season.set()
            result = await task

        assert result.covered_combos == {
            ("2024-25", "Regular Season"),
            ("2024-25", "Playoffs"),
        }

    async def test_broad_game_transport_outage_uses_bounded_canary_and_honors_concurrency(self):
        seasons = ["2023-24", "2024-25"]
        season_types = ["Regular Season", "Playoffs"]
        combos = [(season, season_type) for season in seasons for season_type in season_types]
        barrier = Barrier(2)
        lock = Lock()
        calls: list[tuple[str, str]] = []
        active = 0
        max_active = 0

        def _side_effect(*_args, **kwargs):
            nonlocal active, max_active
            combo = (kwargs["season"], kwargs["season_type"])
            with lock:
                calls.append(combo)
                is_fast_pass = len(calls) <= len(combos)
                active += 1
                max_active = max(max_active, active)
            try:
                if is_fast_pass:
                    barrier.wait(timeout=5)
                raise ConnectionError("broad outage")
            finally:
                with lock:
                    active -= 1

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
        with (
            patch("nba_api.stats.library.http.NBAStatsHTTP.set_session") as set_session,
            patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect),
        ):
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_game_ids_result(
                seasons,
                season_types=season_types,
            )

        assert result.requested_combos == set(combos)
        assert result.covered_combos == frozenset()
        assert Counter(calls) == Counter(
            {
                ("2023-24", "Regular Season"): 1 + _BROAD_OUTAGE_CANARY_ATTEMPTS_CAP,
                ("2023-24", "Playoffs"): 1,
                ("2024-25", "Regular Season"): 1,
                ("2024-25", "Playoffs"): 1,
            }
        )
        assert result.failures_by_combo == {combo: "transport" for combo in combos}
        assert max_active == 2
        set_session.assert_not_called()

    async def test_broad_game_response_outage_uses_bounded_canary_without_serial_fanout(self):
        seasons = ["2023-24", "2024-25"]
        season_types = ["Regular Season", "Playoffs"]
        combos = [(season, season_type) for season in seasons for season_type in season_types]
        calls: list[tuple[str, str]] = []

        def _side_effect(*_args, **kwargs):
            calls.append((kwargs["season"], kwargs["season_type"]))
            return pl.DataFrame({"game_date": ["2025-01-01"]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_game_ids_result(
                seasons,
                season_types=season_types,
            )

        assert Counter(calls) == Counter(
            {
                combos[0]: 1 + _BROAD_OUTAGE_CANARY_ATTEMPTS_CAP,
                combos[1]: 1,
                combos[2]: 1,
                combos[3]: 1,
            }
        )
        assert result.covered_combos == frozenset()
        assert result.failures_by_combo == {combo: "response" for combo in combos}

    async def test_mixed_broad_game_outage_isolates_failure_class_canaries(self):
        seasons = ["2023-24", "2024-25"]
        season_types = ["Regular Season", "Playoffs"]
        combos = [(season, season_type) for season in seasons for season_type in season_types]
        calls: Counter[tuple[str, str]] = Counter()
        transport_combos = {combo for combo in combos if combo[1] == "Regular Season"}
        response_combos = set(combos) - transport_combos

        def _side_effect(*_args, **kwargs):
            combo = (kwargs["season"], kwargs["season_type"])
            calls[combo] += 1
            if combo in response_combos:
                return pl.DataFrame({"game_date": ["2025-01-01"]})
            if calls[combo] == 1:
                raise ConnectionError("transport outage")
            return pl.DataFrame({"game_id": [combo[0]], "game_date": ["2025-01-01"]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_game_ids_result(
                seasons,
                season_types=season_types,
            )

        assert calls == Counter(
            {
                ("2023-24", "Regular Season"): 2,
                ("2023-24", "Playoffs"): 1 + _BROAD_OUTAGE_CANARY_ATTEMPTS_CAP,
                ("2024-25", "Regular Season"): 2,
                ("2024-25", "Playoffs"): 1,
            }
        )
        assert result.covered_combos == transport_combos
        assert result.failures_by_combo == {combo: "response" for combo in response_combos}

    async def test_broad_game_canary_survives_two_transient_failures_before_recovery(self):
        combos = [
            ("2023-24", "Regular Season"),
            ("2024-25", "Regular Season"),
        ]
        call_counts: Counter[tuple[str, str]] = Counter()
        call_kwargs: list[dict[str, object]] = []

        def _side_effect(*_args, **kwargs):
            combo = (kwargs["season"], kwargs["season_type"])
            call_counts[combo] += 1
            call_kwargs.append(dict(kwargs))
            if call_counts[combo] == 1:
                raise ConnectionError("initial route outage")
            if combo == combos[0] and call_counts[combo] < 4:
                raise ConnectionError("route still converging")
            return pl.DataFrame({"game_id": [combo[0]], "game_date": ["2025-01-01"]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_game_ids_result(
                [combo[0] for combo in combos],
                season_types=["Regular Season"],
            )

        assert result.covered_combos == frozenset(combos)
        assert result.failures_by_combo == {}
        assert call_counts == Counter({combos[0]: 4, combos[1]: 2})
        assert [
            kwargs["timeout"]
            for kwargs in call_kwargs
            if (kwargs["season"], kwargs["season_type"]) == combos[0]
        ] == [_CONCURRENT_DISCOVERY_TIMEOUT] * 4
        assert [
            kwargs["timeout"]
            for kwargs in call_kwargs
            if (kwargs["season"], kwargs["season_type"]) == combos[1]
        ] == [_CONCURRENT_DISCOVERY_TIMEOUT, _RECOVERY_DISCOVERY_TIMEOUT]

    async def test_does_not_recover_permanent_game_failures(self):
        combos = {
            ("2024-25", "Regular Season"),
            ("2024-25", "Playoffs"),
        }

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
        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=ExtractionError("permanent"),
        ) as sync_extract:
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_game_ids_result(
                ["2024-25"],
                season_types=["Regular Season", "Playoffs"],
            )

        assert result.requested_combos == combos
        assert result.covered_combos == frozenset()
        assert result.failures_by_combo == {combo: "permanent" for combo in combos}
        assert sync_extract.call_count == len(combos)

    async def test_game_response_shape_failures_use_exact_attempt_budget(self):
        call_kwargs: list[dict[str, object]] = []

        def _side_effect(*_args, **kwargs):
            call_kwargs.append(dict(kwargs))
            return pl.DataFrame({"game_date": ["2025-01-01"]})

        class _Ext:
            pass

        reg = MagicMock()
        reg.get.return_value = _Ext
        settings = SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=2,
            extract_retry_base_delay=0.0,
        )
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_side_effect):
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            result = await disc.discover_game_ids_result(["2024-25"])

        assert result.requested_combos == {("2024-25", "Regular Season")}
        assert result.covered_combos == frozenset()
        assert len(call_kwargs) == settings.extract_max_retries + 1
        assert [kwargs.get("timeout") for kwargs in call_kwargs] == [
            _CONCURRENT_DISCOVERY_TIMEOUT,
            _RECOVERY_DISCOVERY_TIMEOUT,
            _RECOVERY_DISCOVERY_TIMEOUT,
        ]
        assert result.failures_by_combo == {("2024-25", "Regular Season"): "response"}

    async def test_uses_shorter_timeout_during_concurrent_game_sweep(self):
        call_kwargs: list[dict[str, object]] = []

        def _side_effect(*_args, **kwargs):
            call_kwargs.append(dict(kwargs))
            if len(call_kwargs) <= 2:
                raise ConnectionError("fail")
            return pl.DataFrame({"game_id": ["001"], "game_date": ["2025-01-01"]})

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
            disc = EntityDiscovery(reg, settings=_as_settings(settings))
            ids, combined = await disc.discover_game_ids(
                ["2024-25"],
                season_types=["Regular Season"],
            )

        assert ids == ["001"]
        assert combined.shape[0] == 1
        assert [kwargs.get("timeout") for kwargs in call_kwargs] == [
            _CONCURRENT_DISCOVERY_TIMEOUT,
            _RECOVERY_DISCOVERY_TIMEOUT,
            _RECOVERY_DISCOVERY_TIMEOUT,
        ]

    async def test_failure_in_one_season_does_not_cancel_others(self):
        call_count = 0

        def _side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("fail")
            return pl.DataFrame({"game_id": ["002"], "game_date": ["2025-01-01"]})

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
        df = pl.DataFrame({"game_id": ["001"], "game_date": ["2025-01-01"]})

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


class TestEntityDiscoveryCapture:
    def _registry(self) -> MagicMock:
        registry = MagicMock()
        registry.get.return_value = _CaptureAwareExtractor
        return registry

    def _settings(self, *, retries: int = 0) -> SimpleNamespace:
        return SimpleNamespace(
            rate_limit=1000.0,
            discovery_concurrency=1,
            extract_max_retries=retries,
            extract_retry_base_delay=0.0,
        )

    def test_capture_requires_paired_factory_and_durable_completion_sink(self):
        harness = _DiscoveryCaptureHarness()

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="requires both a contract factory and a durable completion sink",
        ):
            EntityDiscovery(
                self._registry(),
                capture_contract_factory=harness.contract_for,
            )
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="requires both a contract factory and a durable completion sink",
        ):
            EntityDiscovery(
                self._registry(),
                capture_completion_sink=harness.complete,
            )

    async def test_call_admission_precedes_registry_capture_extractor_and_provider(self):
        harness = _DiscoveryCaptureHarness()
        events: list[str] = []

        class _OrderedCaptureExtractor(_CaptureAwareExtractor):
            def __init__(self) -> None:
                events.append("extractor")
                super().__init__()

        registry = MagicMock()

        def registry_get(endpoint_name: str) -> type[_OrderedCaptureExtractor]:
            events.append("registry")
            assert endpoint_name == "common_team_years"
            return _OrderedCaptureExtractor

        def admit(
            endpoint_name: str,
            params: dict[str, object],
            result_route_ids: tuple[str, ...],
        ) -> None:
            events.append("admission")
            assert (endpoint_name, params, result_route_ids) == (
                "common_team_years",
                {},
                ("common_team_years:stg_team_years:0",),
            )

        def capture_factory(
            endpoint_name: str,
            params: dict[str, object],
        ) -> NbaApiCaptureContract:
            events.append("capture")
            return harness.contract_for(endpoint_name, params)

        def provider(extractor: _OrderedCaptureExtractor, **_kwargs: object) -> pl.DataFrame:
            events.append("provider")
            _record_capture_attempt(extractor, successful=True)
            return pl.DataFrame({"team_id": [10]})

        registry.get.side_effect = registry_get
        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=provider):
            result = await EntityDiscovery(
                registry,
                settings=_as_settings(self._settings()),
                capture_contract_factory=capture_factory,
                capture_completion_sink=harness.complete,
                call_admission=admit,
            ).discover_team_ids()

        assert result == [10]
        assert events == [
            "admission",
            "registry",
            "capture",
            "extractor",
            "provider",
        ]

    async def test_rejected_call_has_no_discovery_side_effects(self):
        events: list[str] = []
        registry = MagicMock()
        capture_factory = MagicMock()
        completion_sink = MagicMock()

        def reject(
            endpoint_name: str,
            params: dict[str, object],
            result_route_ids: tuple[str, ...],
        ) -> None:
            events.append("admission")
            assert (endpoint_name, params, result_route_ids) == (
                "common_team_years",
                {},
                ("common_team_years:stg_team_years:0",),
            )
            raise RuntimeError("outside intent")

        with (
            patch("nbadb.orchestrate.discovery._sync_extract") as provider,
            pytest.raises(RuntimeError, match="outside intent"),
        ):
            await EntityDiscovery(
                registry,
                settings=_as_settings(self._settings()),
                capture_contract_factory=capture_factory,
                capture_completion_sink=completion_sink,
                call_admission=reject,
            ).discover_team_ids()

        assert events == ["admission"]
        registry.get.assert_not_called()
        capture_factory.assert_not_called()
        provider.assert_not_called()
        completion_sink.assert_not_called()

    async def test_success_records_exact_team_params_route_and_completion(self):
        harness = _DiscoveryCaptureHarness()
        frame = pl.DataFrame({"team_id": [20, 10]})

        def _success(extractor: _CaptureAwareExtractor, **_kwargs: object) -> pl.DataFrame:
            context = _record_capture_attempt(extractor, successful=True)
            assert (context.retry_ordinal, context.request_ordinal) == (0, 0)
            return frame

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_success):
            result = await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings()),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=harness.complete,
            ).discover_team_ids()

        assert result == [10, 20]
        assert harness.factory_calls == [("common_team_years", {})]
        assert len(harness.completions) == 1
        completion = harness.completions[0]
        assert completion.endpoint_name == "common_team_years"
        assert completion.parameters == {}
        assert completion.frame.equals(frame)
        assert completion.scope_key == DiscoveryCaptureScopeKey(
            "common_team_years",
            canonical_parameters_sha256({}),
        )
        assert completion.receipt_binding.result_route_ids == (
            "common_team_years:stg_team_years:0",
        )
        assert harness.sink.logical_calls[0]["logical_parameters"] == {}
        assert harness.sink.logical_calls[0]["result_route_ids"] == (
            "common_team_years:stg_team_years:0",
        )

    async def test_retry_reuses_one_logical_call_with_exact_retry_ordinals(self):
        harness = _DiscoveryCaptureHarness()
        frame = pl.DataFrame({"person_id": [2, 1], "roster_status": [1, 1]})
        observed_contexts: list[tuple[int, int]] = []

        def _retry_then_success(
            extractor: _CaptureAwareExtractor,
            **_kwargs: object,
        ) -> pl.DataFrame:
            successful = len(observed_contexts) == 1
            context = _record_capture_attempt(extractor, successful=successful)
            observed_contexts.append((context.retry_ordinal, context.request_ordinal))
            if not successful:
                raise ConnectionError("retry")
            return frame

        with patch(
            "nbadb.orchestrate.discovery._sync_extract",
            side_effect=_retry_then_success,
        ):
            result = await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings(retries=1)),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=harness.complete,
            ).discover_player_ids("2024-25")

        assert result == [1, 2]
        assert harness.factory_calls == [("common_all_players", {"season": "2024-25"})]
        assert observed_contexts == [(0, 0), (1, 0)]
        assert len(harness.completions) == 1
        logical_call = harness.sink.logical_calls[0]
        assert logical_call["logical_parameters"] == {"season": "2024-25"}
        assert logical_call["successful_response_ordinals"] == (1,)
        assert logical_call["result_route_ids"] == ("common_all_players:stg_common_all_players:0",)

    async def test_terminal_failure_seals_attempts_without_completion(self):
        harness = _DiscoveryCaptureHarness()
        observed_retry_ordinals: list[int] = []

        def _failure(extractor: _CaptureAwareExtractor, **_kwargs: object) -> pl.DataFrame:
            context = _record_capture_attempt(extractor, successful=False)
            observed_retry_ordinals.append(context.retry_ordinal)
            raise ConnectionError("offline")

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_failure):
            result = await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings(retries=1)),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=harness.complete,
            ).discover_team_ids()

        assert result == []
        assert observed_retry_ordinals == [0, 1]
        assert harness.completions == []
        assert harness.sink.logical_calls == []
        snapshot = harness.contracts[0].receipt_snapshot()
        assert snapshot.successful_response_ordinals == ()
        assert len(snapshot.entries) == 2

    async def test_cancellation_propagates_without_completion(self):
        harness = _DiscoveryCaptureHarness()

        def _cancel(extractor: _CaptureAwareExtractor, **_kwargs: object) -> pl.DataFrame:
            _record_capture_attempt(extractor, successful=False)
            raise asyncio.CancelledError

        with (
            patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_cancel),
            pytest.raises(asyncio.CancelledError),
        ):
            await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings()),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=harness.complete,
            ).discover_team_ids()

        assert harness.completions == []
        assert harness.sink.logical_calls == []
        assert harness.contracts[0].receipt_snapshot().successful_response_ordinals == ()

    async def test_success_without_parser_receipt_fails_closed(self):
        harness = _DiscoveryCaptureHarness()
        frame = pl.DataFrame({"team_id": [10]})

        with (
            patch("nbadb.orchestrate.discovery._sync_extract", return_value=frame),
            pytest.raises(
                ParserInputCaptureIntegrityError,
                match="cannot seal without requests",
            ),
        ):
            await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings()),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=harness.complete,
            ).discover_team_ids()

        assert harness.completions == []
        assert harness.sink.logical_calls == []

    async def test_direct_league_path_persists_before_completion_and_exposes_binding(self):
        harness = _DiscoveryCaptureHarness()
        frame = pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2024-10-22"]})
        events: list[str] = []

        def _success(extractor: _CaptureAwareExtractor, **kwargs: object) -> pl.DataFrame:
            assert kwargs == {
                "season": "2024-25",
                "season_type": "Playoffs",
                "timeout": _CONCURRENT_DISCOVERY_TIMEOUT,
            }
            _record_capture_attempt(extractor, successful=True)
            return frame

        def _persist(
            combo: tuple[str, str],
            persisted_frame: pl.DataFrame,
        ) -> None:
            assert combo == ("2024-25", "Playoffs")
            assert persisted_frame.equals(frame)
            events.append("persisted")

        def _complete(completion: DiscoveryCaptureCompletion) -> None:
            assert events == ["persisted"]
            events.append("completed")
            harness.complete(completion)

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_success):
            result = await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings()),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=_complete,
            ).discover_game_ids_result(
                ["2024-25"],
                season_types=["Playoffs"],
                on_combo_covered=_persist,
            )

        logical_params: dict[str, object] = {
            "season": "2024-25",
            "season_type": "Playoffs",
        }
        scope_key = DiscoveryCaptureScopeKey.from_parameters(
            "league_game_log",
            logical_params,
        )
        assert events == ["persisted", "completed"]
        assert harness.factory_calls == [("league_game_log", logical_params)]
        assert result.frames_by_combo[("2024-25", "Playoffs")].equals(frame)
        assert result.capture_bindings_by_scope == {
            scope_key: harness.completions[0].receipt_binding
        }
        assert harness.completions[0].parameters == logical_params
        assert harness.completions[0].receipt_binding.result_route_ids == (
            "league_game_log:stg_league_game_log:0",
        )

    async def test_league_persistence_failure_prevents_completion(self):
        harness = _DiscoveryCaptureHarness()
        frame = pl.DataFrame({"game_id": ["0022400001"], "game_date": ["2024-10-22"]})

        def _success(extractor: _CaptureAwareExtractor, **_kwargs: object) -> pl.DataFrame:
            _record_capture_attempt(extractor, successful=True)
            return frame

        def _persist_failure(
            _combo: tuple[str, str],
            _frame: pl.DataFrame,
        ) -> None:
            raise RuntimeError("durable discovery write failed")

        with (
            patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_success),
            pytest.raises(RuntimeError, match="durable discovery write failed"),
        ):
            await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings()),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=harness.complete,
            ).discover_game_ids_result(
                ["2024-25"],
                on_combo_covered=_persist_failure,
            )

        assert harness.completions == []
        assert len(harness.sink.logical_calls) == 1

    async def test_player_team_result_exposes_canonical_binding_inventory(self):
        harness = _DiscoveryCaptureHarness()
        source_frame = pl.DataFrame({"player_id": [2, 1], "team_id": [20, 10]})

        def _success(extractor: _CaptureAwareExtractor, **_kwargs: object) -> pl.DataFrame:
            _record_capture_attempt(extractor, successful=True)
            return source_frame

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_success):
            result = await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings()),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=harness.complete,
            ).discover_player_team_season_params_result(
                ["2024-25"],
                season_types=["Regular Season"],
            )

        params: dict[str, object] = {
            "season": "2024-25",
            "season_type": "Regular Season",
        }
        scope_key = DiscoveryCaptureScopeKey.from_parameters("player_game_logs", params)
        assert harness.factory_calls == [("player_game_logs", params)]
        assert result.capture_bindings_by_scope == {
            scope_key: harness.completions[0].receipt_binding
        }
        assert harness.completions[0].frame.to_dicts() == [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
        ]
        assert harness.completions[0].receipt_binding.result_route_ids == (
            "player_game_logs:stg_player_game_logs:0",
        )

    async def test_player_fallback_merges_canonical_binding_inventory_and_exact_params(self):
        harness = _DiscoveryCaptureHarness()
        responses = [
            pl.DataFrame(
                {
                    "person_id": [1],
                    "from_year": [None],
                    "to_year": [None],
                }
            ),
            pl.DataFrame(
                {
                    "person_id": [2],
                    "from_year": ["1946"],
                    "to_year": ["1946"],
                }
            ),
        ]

        def _success(extractor: _CaptureAwareExtractor, **_kwargs: object) -> pl.DataFrame:
            _record_capture_attempt(extractor, successful=True)
            return responses.pop(0)

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_success):
            result = await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings()),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=harness.complete,
            ).discover_all_player_ids_result("1946-47")

        assert result.ids == [2]
        assert harness.factory_calls == [
            ("common_all_players", {}),
            ("player_index", {"season": "1946-47"}),
        ]
        expected_scopes = {
            DiscoveryCaptureScopeKey.from_parameters("common_all_players", {}),
            DiscoveryCaptureScopeKey.from_parameters(
                "player_index",
                {"season": "1946-47"},
            ),
        }
        assert set(result.capture_bindings_by_scope) == expected_scopes
        assert [
            completion.receipt_binding.result_route_ids for completion in harness.completions
        ] == [
            ("common_all_players:stg_common_all_players:0",),
            ("player_index:stg_player_index:0",),
        ]

    async def test_bulk_player_directory_call_uses_exact_empty_logical_params(self):
        harness = _DiscoveryCaptureHarness()
        frame = pl.DataFrame(
            {
                "person_id": [2],
                "from_year": ["1946"],
                "to_year": ["1947"],
            }
        )

        def _success(extractor: _CaptureAwareExtractor, **_kwargs: object) -> pl.DataFrame:
            _record_capture_attempt(extractor, successful=True)
            return frame

        with patch("nbadb.orchestrate.discovery._sync_extract", side_effect=_success):
            result = await EntityDiscovery(
                self._registry(),
                settings=_as_settings(self._settings()),
                capture_contract_factory=harness.contract_for,
                capture_completion_sink=harness.complete,
            ).discover_all_player_ids_by_season(["1946-47", "1947-48"])

        assert result == {"1946-47": [2], "1947-48": [2]}
        assert harness.factory_calls == [("common_all_players", {})]
        assert harness.completions[0].parameters == {}
