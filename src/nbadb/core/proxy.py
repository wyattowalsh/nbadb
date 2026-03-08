"""Thin proxy-pool wrapper isolating the proxywhirl dependency."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nbadb.core.config import NbaDbSettings


class SimpleProxyRotator:
    """Lightweight round-robin rotator for explicit proxy URLs.

    Bypasses proxywhirl entirely — suitable for premium/SOCKS5 proxies
    where bootstrap discovery and circuit breakers are unnecessary.
    """

    def __init__(self, urls: list[str]) -> None:
        self._urls = list(urls)
        self._index = 0

    def get_proxy_url(self) -> str | None:
        """Return the next proxy URL, cycling round-robin."""
        if not self._urls:
            return None
        url = self._urls[self._index % len(self._urls)]
        self._index += 1
        return url

    @property
    def size(self) -> int:
        """Number of proxies in the rotator."""
        return len(self._urls)


class ProxyPool:
    """Proxy URL provider backed by proxywhirl."""

    def __init__(self, whirl: object) -> None:
        self._whirl = whirl

    @classmethod
    def from_settings(cls, settings: NbaDbSettings) -> ProxyPool:
        """Build a ProxyWhirl instance from NbaDbSettings."""
        from proxywhirl import (
            ALL_SOURCES,
            RECOMMENDED_SOURCES,
            BootstrapConfig,
            Proxy,
            ProxyConfiguration,
            ProxyWhirl,
        )

        config = ProxyConfiguration(
            timeout=settings.proxy_timeout,
            max_retries=settings.proxy_max_retries,
        )

        proxies: list[Proxy] | None = None
        bootstrap: BootstrapConfig | None = None

        if settings.proxy_urls:
            proxies = [Proxy(url=u) for u in settings.proxy_urls]
            logger.info("proxy pool: {} explicit proxies", len(proxies))
        elif settings.proxy_bootstrap:
            sources = ALL_SOURCES if settings.proxy_use_all_sources else RECOMMENDED_SOURCES
            bootstrap = BootstrapConfig(
                enabled=True,
                sources=sources,
                sample_size=settings.proxy_bootstrap_sample_size,
                validate_proxies=True,
            )
            logger.info(
                "proxy pool: bootstrapping from {} sources",
                len(sources),
            )
        else:
            bootstrap = BootstrapConfig(enabled=False)

        whirl = ProxyWhirl(
            proxies=proxies,
            strategy=settings.proxy_strategy,
            config=config,
            bootstrap=bootstrap,
        )

        pool = cls(whirl)
        if settings.proxy_urls:
            logger.info("proxy pool ready: {} explicit proxies", pool.size)
        elif settings.proxy_bootstrap:
            logger.info("proxy pool: running bootstrap discovery...")
            whirl._bootstrap_pool_if_empty()
            logger.info("proxy pool ready: {} bootstrapped proxies", pool.size)
        return pool

    def get_proxy_url(self) -> str | None:
        """Return the next proxy URL string, or None if pool empty."""
        from proxywhirl import ProxyPoolEmptyError

        try:
            proxy = self._whirl._select_proxy_with_circuit_breaker()
            return proxy.url
        except ProxyPoolEmptyError:
            logger.debug("proxy pool empty, falling back to direct")
            return None
        except Exception as exc:
            logger.warning("proxy selection failed: {}", type(exc).__name__)
            return None

    @property
    def size(self) -> int:
        """Number of proxies currently in the pool."""
        stats = self._whirl.get_pool_stats()
        return stats.get("total_proxies", 0)


_NORDVPN_SOCKS5_HOSTS = [
    "us.socks.nordhold.net",
    "atlanta.us.socks.nordhold.net",
    "dallas.us.socks.nordhold.net",
    "los-angeles.us.socks.nordhold.net",
    "new-york.us.socks.nordhold.net",
    "chicago.us.socks.nordhold.net",
]


def _build_socks5_urls(user: str, password: str) -> list[str]:
    """Construct SOCKS5 proxy URLs from credentials and NordVPN hosts."""
    return [
        f"socks5h://{user}:{password}@{host}:1080"
        for host in _NORDVPN_SOCKS5_HOSTS
    ]


def build_proxy_pool(settings: NbaDbSettings) -> SimpleProxyRotator | ProxyPool | None:
    """Build a proxy pool from settings, or return None if disabled.

    Priority:
    1. Explicit ``proxy_urls`` → SimpleProxyRotator
    2. ``proxy_user`` + ``proxy_pass`` → build SOCKS5 URLs → SimpleProxyRotator
    3. ``proxy_bootstrap`` → proxywhirl ProxyPool
    """
    if not settings.proxy_enabled:
        return None
    urls = list(settings.proxy_urls)
    if not urls and settings.proxy_user and settings.proxy_pass:
        urls = _build_socks5_urls(settings.proxy_user, settings.proxy_pass)
        logger.info("proxy: built {} SOCKS5 URLs from credentials", len(urls))
    if urls:
        logger.info("proxy: using SimpleProxyRotator with {} URLs", len(urls))
        return SimpleProxyRotator(urls)
    if settings.proxy_bootstrap:
        return ProxyPool.from_settings(settings)
    return None
