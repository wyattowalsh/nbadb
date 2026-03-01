"""Thin proxy-pool wrapper isolating the proxywhirl dependency."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nbadb.core.config import NbaDbSettings


class ProxyPool:
    """Proxy URL provider backed by proxywhirl."""

    def __init__(self, whirl: object) -> None:
        self._whirl = whirl

    @classmethod
    def from_settings(cls, settings: NbaDbSettings) -> ProxyPool:
        """Build a ProxyWhirl instance from NbaDbSettings."""
        from proxywhirl import (
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
            logger.info(
                "proxy pool: {} explicit proxies", len(proxies)
            )
        elif settings.proxy_bootstrap:
            bootstrap = BootstrapConfig(
                enabled=True,
                sources=RECOMMENDED_SOURCES,
                sample_size=settings.proxy_bootstrap_sample_size,
                validate_proxies=True,
            )
            logger.info(
                "proxy pool: bootstrapping from {} recommended sources",
                len(RECOMMENDED_SOURCES),
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
            logger.info(
                "proxy pool ready: {} explicit proxies", pool.size
            )
        else:
            logger.info(
                "proxy pool: bootstrap enabled, fetching on first use"
            )
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
            logger.warning("proxy selection failed: {}", exc)
            return None

    @property
    def size(self) -> int:
        """Number of proxies currently in the pool."""
        stats = self._whirl.get_pool_stats()
        return stats.get("total_proxies", 0)


def build_proxy_pool(settings: NbaDbSettings) -> ProxyPool | None:
    """Build a proxy pool from settings, or return None if disabled."""
    if not settings.proxy_enabled:
        return None
    return ProxyPool.from_settings(settings)
