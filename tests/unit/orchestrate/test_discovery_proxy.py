from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl

from nbadb.orchestrate.discovery import EntityDiscovery, _assign_proxy


class TestAssignProxy:
    def test_assigns_url_when_pool_present(self) -> None:
        mock_pool = MagicMock()
        mock_pool.get_proxy_url.return_value = "http://1.2.3.4:8080"
        mock_extractor = MagicMock()

        _assign_proxy(mock_extractor, mock_pool)

        assert mock_extractor._proxy_url == "http://1.2.3.4:8080"
        mock_pool.get_proxy_url.assert_called_once()

    def test_no_op_when_pool_is_none(self) -> None:
        mock_extractor = MagicMock(spec=[])  # no attributes defined
        _assign_proxy(mock_extractor, None)

        # _proxy_url must not have been set by _assign_proxy
        assert not hasattr(mock_extractor, "_proxy_url")

    def test_assigns_none_url_when_pool_returns_none(self) -> None:
        mock_pool = MagicMock()
        mock_pool.get_proxy_url.return_value = None
        mock_extractor = MagicMock()

        _assign_proxy(mock_extractor, mock_pool)

        assert mock_extractor._proxy_url is None
        mock_pool.get_proxy_url.assert_called_once()

    def test_get_proxy_url_not_called_when_pool_is_none(self) -> None:
        """Ensure pool.get_proxy_url() is never invoked with a None pool."""
        mock_extractor = MagicMock(spec=[])
        _assign_proxy(mock_extractor, None)

        # _proxy_url must not have been set on the extractor
        assert not hasattr(mock_extractor, "_proxy_url")


class TestEntityDiscoveryProxy:
    """Integration-style tests that mock _extract_with_retry and _assign_proxy."""

    # ------------------------------------------------------------------
    # discover_game_ids
    # ------------------------------------------------------------------

    def test_discover_game_ids_assign_proxy_called_with_pool(self) -> None:
        """_assign_proxy is called with the extractor and the proxy pool."""
        game_log_df = pl.DataFrame({"game_id": ["0022400001", "0022400002"]})

        with (
            patch(
                "nbadb.orchestrate.discovery._extract_with_retry",
                new_callable=AsyncMock,
            ) as mock_retry,
            patch("nbadb.orchestrate.discovery._assign_proxy") as mock_assign,
        ):
            mock_retry.return_value = game_log_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            mock_pool = MagicMock()
            discovery = EntityDiscovery(registry, proxy_pool=mock_pool)

            asyncio.run(discovery.discover_game_ids(["2024-25"]))

            mock_assign.assert_called_once_with(mock_extractor, mock_pool)

    def test_discover_game_ids_assign_proxy_called_with_none_pool(self) -> None:
        """_assign_proxy is called with None pool when no pool is provided."""
        game_log_df = pl.DataFrame({"game_id": ["0022400001"]})

        with (
            patch(
                "nbadb.orchestrate.discovery._extract_with_retry",
                new_callable=AsyncMock,
            ) as mock_retry,
            patch("nbadb.orchestrate.discovery._assign_proxy") as mock_assign,
        ):
            mock_retry.return_value = game_log_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            discovery = EntityDiscovery(registry, proxy_pool=None)

            asyncio.run(discovery.discover_game_ids(["2024-25"]))

            mock_assign.assert_called_once_with(mock_extractor, None)

    def test_discover_game_ids_proxy_called_per_season(self) -> None:
        """_assign_proxy is invoked once per season in the loop."""
        game_log_df = pl.DataFrame({"game_id": ["0022400001"]})

        with (
            patch(
                "nbadb.orchestrate.discovery._extract_with_retry",
                new_callable=AsyncMock,
            ) as mock_retry,
            patch("nbadb.orchestrate.discovery._assign_proxy") as mock_assign,
        ):
            mock_retry.return_value = game_log_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            mock_pool = MagicMock()
            discovery = EntityDiscovery(registry, proxy_pool=mock_pool)

            asyncio.run(discovery.discover_game_ids(["2023-24", "2024-25"]))

            assert mock_assign.call_count == 2
            mock_assign.assert_called_with(mock_extractor, mock_pool)

    # ------------------------------------------------------------------
    # discover_player_ids
    # ------------------------------------------------------------------

    def test_discover_player_ids_assign_proxy_called_with_pool(self) -> None:
        player_df = pl.DataFrame({"person_id": [1, 2, 3]})

        with (
            patch(
                "nbadb.orchestrate.discovery._extract_with_retry",
                new_callable=AsyncMock,
            ) as mock_retry,
            patch("nbadb.orchestrate.discovery._assign_proxy") as mock_assign,
        ):
            mock_retry.return_value = player_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            mock_pool = MagicMock()
            discovery = EntityDiscovery(registry, proxy_pool=mock_pool)

            result = asyncio.run(discovery.discover_player_ids(season="2024-25"))

            mock_assign.assert_called_once_with(mock_extractor, mock_pool)
            assert result == [1, 2, 3]

    def test_discover_player_ids_assign_proxy_called_with_none_pool(self) -> None:
        player_df = pl.DataFrame({"person_id": [10, 20]})

        with (
            patch(
                "nbadb.orchestrate.discovery._extract_with_retry",
                new_callable=AsyncMock,
            ) as mock_retry,
            patch("nbadb.orchestrate.discovery._assign_proxy") as mock_assign,
        ):
            mock_retry.return_value = player_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            discovery = EntityDiscovery(registry, proxy_pool=None)

            asyncio.run(discovery.discover_player_ids())

            mock_assign.assert_called_once_with(mock_extractor, None)

    # ------------------------------------------------------------------
    # discover_player_team_season_params
    # ------------------------------------------------------------------

    def test_discover_player_team_season_params_assign_proxy_called_with_pool(self) -> None:
        player_df = pl.DataFrame({"person_id": [1, 2], "team_id": [10, 20]})

        with (
            patch(
                "nbadb.orchestrate.discovery._extract_with_retry",
                new_callable=AsyncMock,
            ) as mock_retry,
            patch("nbadb.orchestrate.discovery._assign_proxy") as mock_assign,
        ):
            mock_retry.return_value = player_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            mock_pool = MagicMock()
            discovery = EntityDiscovery(registry, proxy_pool=mock_pool)

            result = asyncio.run(
                discovery.discover_player_team_season_params(["2024-25", "2025-26"])
            )

            assert mock_assign.call_count == 2
            mock_assign.assert_called_with(mock_extractor, mock_pool)
            assert result == [
                {"player_id": 1, "team_id": 10, "season": "2024-25"},
                {"player_id": 2, "team_id": 20, "season": "2024-25"},
                {"player_id": 1, "team_id": 10, "season": "2025-26"},
                {"player_id": 2, "team_id": 20, "season": "2025-26"},
            ]

    def test_discover_player_team_season_params_assign_proxy_called_with_none_pool(self) -> None:
        player_df = pl.DataFrame({"person_id": [10], "team_id": [20]})

        with (
            patch(
                "nbadb.orchestrate.discovery._extract_with_retry",
                new_callable=AsyncMock,
            ) as mock_retry,
            patch("nbadb.orchestrate.discovery._assign_proxy") as mock_assign,
        ):
            mock_retry.return_value = player_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            discovery = EntityDiscovery(registry, proxy_pool=None)

            asyncio.run(discovery.discover_player_team_season_params(["2024-25"]))

            mock_assign.assert_called_once_with(mock_extractor, None)

    # ------------------------------------------------------------------
    # discover_team_ids
    # ------------------------------------------------------------------

    def test_discover_team_ids_assign_proxy_called_with_pool(self) -> None:
        team_df = pl.DataFrame({"team_id": [1610612737, 1610612738]})

        with (
            patch(
                "nbadb.orchestrate.discovery._extract_with_retry",
                new_callable=AsyncMock,
            ) as mock_retry,
            patch("nbadb.orchestrate.discovery._assign_proxy") as mock_assign,
        ):
            mock_retry.return_value = team_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            mock_pool = MagicMock()
            discovery = EntityDiscovery(registry, proxy_pool=mock_pool)

            result = asyncio.run(discovery.discover_team_ids())

            mock_assign.assert_called_once_with(mock_extractor, mock_pool)
            assert result == [1610612737, 1610612738]

    def test_discover_team_ids_assign_proxy_called_with_none_pool(self) -> None:
        team_df = pl.DataFrame({"team_id": [1610612739]})

        with (
            patch(
                "nbadb.orchestrate.discovery._extract_with_retry",
                new_callable=AsyncMock,
            ) as mock_retry,
            patch("nbadb.orchestrate.discovery._assign_proxy") as mock_assign,
        ):
            mock_retry.return_value = team_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            discovery = EntityDiscovery(registry, proxy_pool=None)

            asyncio.run(discovery.discover_team_ids())

            mock_assign.assert_called_once_with(mock_extractor, None)

    # ------------------------------------------------------------------
    # Proxy URL actually set on extractor (without patching _assign_proxy)
    # ------------------------------------------------------------------

    def test_proxy_url_set_on_extractor_when_pool_present(self) -> None:
        """Real _assign_proxy sets _proxy_url on the extractor instance."""
        game_log_df = pl.DataFrame({"game_id": ["0022400001"]})

        with patch(
            "nbadb.orchestrate.discovery._extract_with_retry",
            new_callable=AsyncMock,
        ) as mock_retry:
            mock_retry.return_value = game_log_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            mock_pool = MagicMock()
            mock_pool.get_proxy_url.return_value = "http://proxy.example.com:3128"

            discovery = EntityDiscovery(registry, proxy_pool=mock_pool)

            asyncio.run(discovery.discover_game_ids(["2024-25"]))

            # _assign_proxy was NOT patched — verify it mutated the extractor
            assert mock_extractor._proxy_url == "http://proxy.example.com:3128"
            mock_pool.get_proxy_url.assert_called_once()

    def test_proxy_url_not_set_when_pool_is_none(self) -> None:
        """With no proxy pool, _assign_proxy must not set _proxy_url."""
        game_log_df = pl.DataFrame({"game_id": ["0022400001"]})

        with patch(
            "nbadb.orchestrate.discovery._extract_with_retry",
            new_callable=AsyncMock,
        ) as mock_retry:
            mock_retry.return_value = game_log_df

            registry = MagicMock()
            # Use spec=[] so attribute access reveals intentional sets only
            mock_extractor = MagicMock(spec=[])
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            discovery = EntityDiscovery(registry, proxy_pool=None)

            asyncio.run(discovery.discover_game_ids(["2024-25"]))

            # _assign_proxy short-circuits when pool is None: no attribute set
            assert not hasattr(mock_extractor, "_proxy_url")

    def test_proxy_url_is_none_when_pool_returns_none(self) -> None:
        """Pool.get_proxy_url() returning None propagates to extractor._proxy_url."""
        game_log_df = pl.DataFrame({"game_id": ["0022400001"]})

        with patch(
            "nbadb.orchestrate.discovery._extract_with_retry",
            new_callable=AsyncMock,
        ) as mock_retry:
            mock_retry.return_value = game_log_df

            registry = MagicMock()
            mock_extractor = MagicMock()
            mock_extractor_cls = MagicMock(return_value=mock_extractor)
            registry.get.return_value = mock_extractor_cls

            mock_pool = MagicMock()
            mock_pool.get_proxy_url.return_value = None

            discovery = EntityDiscovery(registry, proxy_pool=mock_pool)

            asyncio.run(discovery.discover_game_ids(["2024-25"]))

            assert mock_extractor._proxy_url is None
