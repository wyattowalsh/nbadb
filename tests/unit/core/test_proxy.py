from __future__ import annotations

from unittest.mock import MagicMock, patch

from nbadb.core.proxy import ProxyPool


class TestGetProxyUrl:
    def test_returns_url_string(self) -> None:
        mock_whirl = MagicMock()
        mock_proxy = MagicMock()
        mock_proxy.url = "http://1.2.3.4:8080"
        mock_whirl._select_proxy_with_circuit_breaker.return_value = (
            mock_proxy
        )

        pool = ProxyPool(mock_whirl)
        assert pool.get_proxy_url() == "http://1.2.3.4:8080"

    def test_empty_pool_returns_none(self) -> None:
        from proxywhirl import ProxyPoolEmptyError

        mock_whirl = MagicMock()
        mock_whirl._select_proxy_with_circuit_breaker.side_effect = (
            ProxyPoolEmptyError("no proxies")
        )

        pool = ProxyPool(mock_whirl)
        assert pool.get_proxy_url() is None

    def test_rotates_on_successive_calls(self) -> None:
        mock_whirl = MagicMock()
        proxy_a = MagicMock()
        proxy_a.url = "http://1.1.1.1:80"
        proxy_b = MagicMock()
        proxy_b.url = "http://2.2.2.2:80"

        mock_whirl._select_proxy_with_circuit_breaker.side_effect = [
            proxy_a,
            proxy_b,
        ]

        pool = ProxyPool(mock_whirl)
        assert pool.get_proxy_url() == "http://1.1.1.1:80"
        assert pool.get_proxy_url() == "http://2.2.2.2:80"


class TestSize:
    def test_returns_total_proxies(self) -> None:
        mock_whirl = MagicMock()
        mock_whirl.get_pool_stats.return_value = {
            "total_proxies": 42
        }
        pool = ProxyPool(mock_whirl)
        assert pool.size == 42

    def test_defaults_to_zero(self) -> None:
        mock_whirl = MagicMock()
        mock_whirl.get_pool_stats.return_value = {}
        pool = ProxyPool(mock_whirl)
        assert pool.size == 0


class TestFromSettings:
    def test_explicit_urls(self) -> None:
        """When proxy_urls are set, ProxyWhirl gets Proxy objects."""
        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(
            proxy_enabled=True,
            proxy_urls=[
                "http://1.2.3.4:8080",
                "http://5.6.7.8:3128",
            ],
        )

        with patch(
            "proxywhirl.ProxyWhirl"
        ) as mock_pw_cls:
            mock_pw_cls.return_value.get_pool_stats.return_value = {
                "total_proxies": 2
            }
            pool = ProxyPool.from_settings(settings)

            assert pool.size == 2
            call_kwargs = mock_pw_cls.call_args
            assert call_kwargs.kwargs["proxies"] is not None
            assert len(call_kwargs.kwargs["proxies"]) == 2

    def test_bootstrap_mode(self) -> None:
        """When no proxy_urls, bootstrap config is used."""
        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(
            proxy_enabled=True,
            proxy_bootstrap=True,
        )

        with patch(
            "proxywhirl.ProxyWhirl"
        ) as mock_pw_cls:
            mock_pw_cls.return_value.get_pool_stats.return_value = {
                "total_proxies": 5
            }
            ProxyPool.from_settings(settings)

            call_kwargs = mock_pw_cls.call_args
            assert call_kwargs.kwargs["proxies"] is None
            bootstrap = call_kwargs.kwargs["bootstrap"]
            assert bootstrap.enabled is True

    def test_disabled_bootstrap(self) -> None:
        """When bootstrap is off and no URLs, pool bootstraps disabled."""
        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(
            proxy_enabled=True,
            proxy_bootstrap=False,
            proxy_urls=[],
        )

        with patch(
            "proxywhirl.ProxyWhirl"
        ) as mock_pw_cls:
            mock_pw_cls.return_value.get_pool_stats.return_value = {
                "total_proxies": 0
            }
            ProxyPool.from_settings(settings)

            call_kwargs = mock_pw_cls.call_args
            bootstrap = call_kwargs.kwargs["bootstrap"]
            assert bootstrap.enabled is False
