from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger
from proxywhirl import AsyncProxyWhirl, RetryPolicy
from proxywhirl.utils import create_proxy_from_url

from nbadb.core.config import get_settings
from nbadb.core.types import NBA_HEADERS

SEMAPHORE_TIERS: dict[str, int] = {
    "box_score": 10,
    "play_by_play": 5,
    "game_log": 20,
    "player_info": 15,
    "default": 10,
}

_RETRYABLE_STATUS_CODES: set[int] = {429, 502, 503, 504}


class NbaHttpClient:
    """Async HTTP client with proxy rotation for stats.nba.com."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: AsyncProxyWhirl | None = None
        self._semaphores: dict[str, asyncio.Semaphore] = {
            k: asyncio.Semaphore(v) for k, v in SEMAPHORE_TIERS.items()
        }

    async def __aenter__(self) -> NbaHttpClient:
        proxies = await self._load_proxies()
        proxy_objects = [create_proxy_from_url(p) for p in proxies if p]
        self._client = AsyncProxyWhirl(
            proxies=proxy_objects or None,
            strategy="least-used",
            retry_policy=RetryPolicy(
                max_attempts=5,
                base_delay=1.0,
                max_backoff_delay=30.0,
                jitter=True,
                retry_status_codes=[502, 503, 504],
            ),
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.__aexit__(*exc)

    async def _load_proxies(self) -> list[str]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(self._settings.proxy_list_url, timeout=10.0)
                resp.raise_for_status()
                proxies = [line.strip() for line in resp.text.splitlines() if line.strip()]
                logger.info(f"Loaded {len(proxies)} proxies")
                return proxies
        except Exception:
            logger.warning("Failed to load proxies, using direct connection")
            return []

    def _get_semaphore(self, category: str) -> asyncio.Semaphore:
        return self._semaphores.get(category, self._semaphores["default"])

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        category: str = "default",
        headers: dict[str, str] | None = None,
    ) -> Any:
        if not self._client:
            msg = "Client not initialized. Use async with."
            raise RuntimeError(msg)
        merged_headers: dict[str, str] = {**NBA_HEADERS, **(headers or {})}
        sem = self._get_semaphore(category)
        async with sem:
            response: httpx.Response = await self._client.get(
                url, params=params, headers=merged_headers
            )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "2.0"))
                logger.warning(f"Rate-limited (429), backing off {retry_after}s")
                await asyncio.sleep(retry_after)
                response = await self._client.get(url, params=params, headers=merged_headers)
            response.raise_for_status()
            return response.json()
