from __future__ import annotations

from unittest.mock import MagicMock, patch

from nbadb.core.proxy import ProxyPool, SimpleProxyRotator


class TestSimpleProxyRotator:
    def test_round_robin_single_url(self) -> None:
        rotator = SimpleProxyRotator(["socks5h://user:pass@host:1080"])
        assert rotator.get_proxy_url() == "socks5h://user:pass@host:1080"
        assert rotator.get_proxy_url() == "socks5h://user:pass@host:1080"

    def test_round_robin_multiple_urls(self) -> None:
        urls = ["socks5h://a:1080", "socks5h://b:1080", "socks5h://c:1080"]
        rotator = SimpleProxyRotator(urls)
        assert rotator.get_proxy_url() == "socks5h://a:1080"
        assert rotator.get_proxy_url() == "socks5h://b:1080"
        assert rotator.get_proxy_url() == "socks5h://c:1080"
        assert rotator.get_proxy_url() == "socks5h://a:1080"  # wraps

    def test_empty_list_returns_none(self) -> None:
        rotator = SimpleProxyRotator([])
        assert rotator.get_proxy_url() is None

    def test_size(self) -> None:
        assert SimpleProxyRotator(["a", "b"]).size == 2
        assert SimpleProxyRotator([]).size == 0

    def test_preserves_socks5h_scheme(self) -> None:
        url = "socks5h://user:pass@us.socks.nordhold.net:1080"
        rotator = SimpleProxyRotator([url])
        assert rotator.get_proxy_url() == url


class TestGetProxyUrl:
    def test_returns_url_string(self) -> None:
        mock_whirl = MagicMock()
        mock_proxy = MagicMock()
        mock_proxy.url = "http://1.2.3.4:8080"
        mock_whirl._select_proxy_with_circuit_breaker.return_value = mock_proxy

        pool = ProxyPool(mock_whirl)
        assert pool.get_proxy_url() == "http://1.2.3.4:8080"

    def test_empty_pool_returns_none(self) -> None:
        from proxywhirl import ProxyPoolEmptyError

        mock_whirl = MagicMock()
        mock_whirl._select_proxy_with_circuit_breaker.side_effect = ProxyPoolEmptyError(
            "no proxies"
        )

        pool = ProxyPool(mock_whirl)
        assert pool.get_proxy_url() is None

    def test_unexpected_exception_returns_none(self) -> None:
        """Broad except Exception handler returns None, not crash."""
        mock_whirl = MagicMock()
        mock_whirl._select_proxy_with_circuit_breaker.side_effect = RuntimeError("internal error")
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
        mock_whirl.get_pool_stats.return_value = {"total_proxies": 42}
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

        with patch("proxywhirl.ProxyWhirl") as mock_pw_cls:
            mock_pw_cls.return_value.get_pool_stats.return_value = {"total_proxies": 2}
            pool = ProxyPool.from_settings(settings)

            assert pool.size == 2
            call_kwargs = mock_pw_cls.call_args
            assert call_kwargs.kwargs["proxies"] is not None
            assert len(call_kwargs.kwargs["proxies"]) == 2

    def test_bootstrap_mode(self) -> None:
        """When no proxy_urls, bootstrap config is used."""
        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(
            _env_file=None,
            proxy_enabled=True,
            proxy_bootstrap=True,
            proxy_urls=[],
        )

        with patch("proxywhirl.ProxyWhirl") as mock_pw_cls:
            mock_pw_cls.return_value.get_pool_stats.return_value = {"total_proxies": 5}
            ProxyPool.from_settings(settings)

            call_kwargs = mock_pw_cls.call_args
            assert call_kwargs.kwargs["proxies"] is None
            bootstrap = call_kwargs.kwargs["bootstrap"]
            assert bootstrap.enabled is True

    def test_bootstrap_uses_all_sources_by_default(self) -> None:
        """Default proxy_use_all_sources=True selects ALL_SOURCES (114)."""
        from proxywhirl import ALL_SOURCES

        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(
            _env_file=None,
            proxy_enabled=True,
            proxy_bootstrap=True,
            proxy_use_all_sources=True,
            proxy_urls=[],
        )

        with patch("proxywhirl.ProxyWhirl") as mock_pw_cls:
            mock_pw_cls.return_value.get_pool_stats.return_value = {"total_proxies": 10}
            ProxyPool.from_settings(settings)

            call_kwargs = mock_pw_cls.call_args
            bootstrap = call_kwargs.kwargs["bootstrap"]
            assert bootstrap.sources == ALL_SOURCES

    def test_bootstrap_recommended_sources_when_flag_false(self) -> None:
        """proxy_use_all_sources=False selects RECOMMENDED_SOURCES."""
        from proxywhirl import RECOMMENDED_SOURCES

        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(
            _env_file=None,
            proxy_enabled=True,
            proxy_bootstrap=True,
            proxy_use_all_sources=False,
            proxy_urls=[],
        )

        with patch("proxywhirl.ProxyWhirl") as mock_pw_cls:
            mock_pw_cls.return_value.get_pool_stats.return_value = {"total_proxies": 3}
            ProxyPool.from_settings(settings)

            call_kwargs = mock_pw_cls.call_args
            bootstrap = call_kwargs.kwargs["bootstrap"]
            assert bootstrap.sources == RECOMMENDED_SOURCES

    def test_disabled_bootstrap(self) -> None:
        """When bootstrap is off and no URLs, pool bootstraps disabled."""
        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(
            proxy_enabled=True,
            proxy_bootstrap=False,
            proxy_urls=[],
        )

        with patch("proxywhirl.ProxyWhirl") as mock_pw_cls:
            mock_pw_cls.return_value.get_pool_stats.return_value = {"total_proxies": 0}
            ProxyPool.from_settings(settings)

            call_kwargs = mock_pw_cls.call_args
            bootstrap = call_kwargs.kwargs["bootstrap"]
            assert bootstrap.enabled is False


class TestBuildProxyPool:
    def test_disabled_returns_none(self) -> None:
        from nbadb.core.config import NbaDbSettings
        from nbadb.core.proxy import build_proxy_pool

        settings = NbaDbSettings(proxy_enabled=False)
        assert build_proxy_pool(settings) is None

    def test_explicit_urls_no_bootstrap_returns_simple_rotator(self) -> None:
        from nbadb.core.config import NbaDbSettings
        from nbadb.core.proxy import build_proxy_pool

        settings = NbaDbSettings(
            proxy_enabled=True,
            proxy_bootstrap=False,
            proxy_urls=["socks5h://user:pass@host:1080", "http://1.2.3.4:8080"],
        )
        pool = build_proxy_pool(settings)
        assert isinstance(pool, SimpleProxyRotator)
        assert pool.size == 2

    def test_explicit_urls_with_bootstrap_still_returns_simple_rotator(self) -> None:
        """Explicit URLs always use SimpleProxyRotator, even with bootstrap=True."""
        from nbadb.core.config import NbaDbSettings
        from nbadb.core.proxy import build_proxy_pool

        settings = NbaDbSettings(
            proxy_enabled=True,
            proxy_bootstrap=True,
            proxy_urls=["http://1.2.3.4:8080"],
        )
        pool = build_proxy_pool(settings)
        assert isinstance(pool, SimpleProxyRotator)
        assert pool.size == 1

    def test_no_urls_bootstrap_returns_proxypool(self) -> None:
        from nbadb.core.config import NbaDbSettings
        from nbadb.core.proxy import build_proxy_pool

        settings = NbaDbSettings(
            _env_file=None,
            proxy_enabled=True,
            proxy_bootstrap=True,
            proxy_urls=[],
        )
        with patch("proxywhirl.ProxyWhirl") as mock_pw_cls:
            mock_pw_cls.return_value.get_pool_stats.return_value = {"total_proxies": 5}
            pool = build_proxy_pool(settings)
            assert isinstance(pool, ProxyPool)

    def test_no_urls_no_bootstrap_returns_none(self) -> None:
        from nbadb.core.config import NbaDbSettings
        from nbadb.core.proxy import build_proxy_pool

        settings = NbaDbSettings(
            _env_file=None,
            proxy_enabled=True,
            proxy_bootstrap=False,
            proxy_urls=[],
        )
        assert build_proxy_pool(settings) is None

    def test_credentials_build_socks5_urls(self) -> None:
        from nbadb.core.config import NbaDbSettings
        from nbadb.core.proxy import build_proxy_pool

        settings = NbaDbSettings(
            _env_file=None,
            proxy_enabled=True,
            proxy_bootstrap=False,
            proxy_urls=[],
            proxy_user="testuser",
            proxy_pass="testpass",
        )
        pool = build_proxy_pool(settings)
        assert isinstance(pool, SimpleProxyRotator)
        assert pool.size == 6


class TestProxyPoolGetProxyUrl:
    def test_attribute_error_fallback(self) -> None:
        """When private API raises AttributeError, fall back to public get_proxy()."""
        mock_whirl = MagicMock()
        mock_whirl._select_proxy_with_circuit_breaker.side_effect = AttributeError
        mock_proxy = MagicMock()
        mock_proxy.url = "http://fallback:8080"
        mock_whirl.get_proxy.return_value = mock_proxy
        pool = ProxyPool(mock_whirl)
        assert pool.get_proxy_url() == "http://fallback:8080"


class TestGetProxyPublicApi:
    def test_success(self) -> None:
        mock_whirl = MagicMock()
        mock_proxy = MagicMock()
        mock_proxy.url = "http://pub:8080"
        mock_whirl.get_proxy.return_value = mock_proxy
        pool = ProxyPool(mock_whirl)
        assert pool._get_proxy_public_api() == "http://pub:8080"

    def test_returns_none_when_proxy_is_none(self) -> None:
        mock_whirl = MagicMock()
        mock_whirl.get_proxy.return_value = None
        pool = ProxyPool(mock_whirl)
        assert pool._get_proxy_public_api() is None

    def test_returns_none_on_exception(self) -> None:
        mock_whirl = MagicMock()
        mock_whirl.get_proxy.side_effect = RuntimeError("fail")
        pool = ProxyPool(mock_whirl)
        assert pool._get_proxy_public_api() is None


class TestBuildSocks5Urls:
    def test_format_and_count(self) -> None:
        from nbadb.core.proxy import _build_socks5_urls

        urls = _build_socks5_urls("user", "pass")
        assert len(urls) == 6
        assert all(u.startswith("socks5h://user:pass@") for u in urls)
        assert all(u.endswith(":1080") for u in urls)

    def test_special_characters_in_credentials(self) -> None:
        from nbadb.core.proxy import _build_socks5_urls

        urls = _build_socks5_urls("u@ser", "p:ass")
        assert all("u@ser:p:ass@" in u for u in urls)
