from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import polars as pl

    from nbadb.extract.registry import EndpointRegistry

_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 2.0  # seconds between retries


async def _extract_with_retry(
    extractor: object,
    label: str,
    **kwargs: object,
) -> pl.DataFrame:
    """Extract with retries and inter-call delay for rate limiting."""
    import polars as pl

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            df: pl.DataFrame = await asyncio.to_thread(
                _sync_extract, extractor, **kwargs
            )
            return df
        except Exception as exc:
            if attempt < _RETRY_ATTEMPTS:
                delay = _RETRY_DELAY * attempt
                logger.warning(
                    "{}: attempt {}/{} failed ({}), retrying in {:.0f}s",
                    label,
                    attempt,
                    _RETRY_ATTEMPTS,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "{}: all {} attempts failed: {}",
                    label,
                    _RETRY_ATTEMPTS,
                    exc,
                )
                raise
    return pl.DataFrame()  # unreachable, satisfies type checker


class EntityDiscovery:
    """Discovers entity IDs needed for extraction loops."""

    def __init__(self, registry: EndpointRegistry) -> None:
        self._registry = registry

    async def discover_game_ids(
        self, seasons: list[str]
    ) -> tuple[list[str], pl.DataFrame]:
        """Extract league_game_log for given seasons.

        Returns (game_ids, raw_df). The raw_df is also usable as
        stg_league_game_log (dual purpose -- avoids re-extraction).
        """
        import polars as pl

        extractor_cls = self._registry.get("league_game_log")
        extractor = extractor_cls()

        frames: list[pl.DataFrame] = []
        for season in seasons:
            logger.info("discovering game IDs for season {}", season)
            try:
                df = await _extract_with_retry(
                    extractor,
                    f"league_game_log({season})",
                    season=season,
                )
                if not df.is_empty():
                    frames.append(df)
            except Exception as exc:
                logger.error(
                    "failed to extract game log for {}: {}",
                    season,
                    exc,
                )

        if not frames:
            logger.warning("no game log data returned")
            return [], pl.DataFrame()

        combined = pl.concat(frames)
        game_ids = (
            combined.get_column("game_id")
            .unique()
            .sort()
            .to_list()
        )
        logger.info(
            "discovered {} unique game IDs across {} seasons",
            len(game_ids),
            len(seasons),
        )
        return game_ids, combined

    async def discover_player_ids(
        self, season: str | None = None
    ) -> list[int]:
        """Get active player IDs from common_all_players."""
        extractor_cls = self._registry.get("common_all_players")
        extractor = extractor_cls()

        kwargs = {"season": season} if season else {}
        try:
            df = await _extract_with_retry(
                extractor, "common_all_players", **kwargs
            )
        except Exception as exc:
            logger.error(
                "failed to discover player IDs: {}", exc
            )
            return []

        if df.is_empty():
            logger.warning("no player data returned")
            return []

        # Filter to active players when the column exists
        if "is_active" in df.columns:
            df = df.filter(df["is_active"] == 1)

        player_ids: list[int] = (
            df.get_column("person_id").unique().sort().to_list()
        )
        logger.info("discovered {} player IDs", len(player_ids))
        return player_ids

    async def discover_team_ids(self) -> list[int]:
        """Get all team IDs from common_team_years."""
        extractor_cls = self._registry.get("common_team_years")
        extractor = extractor_cls()

        try:
            df = await _extract_with_retry(
                extractor, "common_team_years"
            )
        except Exception as exc:
            logger.error(
                "failed to discover team IDs: {}", exc
            )
            return []

        if df.is_empty():
            logger.warning("no team data returned")
            return []

        team_ids: list[int] = (
            df.get_column("team_id").unique().sort().to_list()
        )
        logger.info("discovered {} team IDs", len(team_ids))
        return team_ids

    async def discover_game_dates(
        self, game_log_df: pl.DataFrame
    ) -> list[str]:
        """Extract unique game dates from an already-fetched game log."""
        import polars as pl

        if game_log_df.is_empty():
            return []

        dates: list[str] = (
            game_log_df.get_column("game_date")
            .cast(pl.Utf8)
            .unique()
            .sort()
            .to_list()
        )
        logger.info("discovered {} unique game dates", len(dates))
        return dates


def _sync_extract(
    extractor: object, **kwargs: object
) -> pl.DataFrame:
    """Call extractor.extract() synchronously (for asyncio.to_thread)."""
    import asyncio

    return asyncio.run(extractor.extract(**kwargs))  # type: ignore[union-attr]
