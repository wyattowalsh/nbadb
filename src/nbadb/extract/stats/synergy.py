from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger
from nba_api.stats.endpoints import SynergyPlayTypes

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

_SYNERGY_PLAY_TYPES = [
    "Isolation",
    "Transition",
    "PRBallHandler",
    "PRRollMan",
    "Postup",
    "Spotup",
    "Handoff",
    "Cut",
    "OffScreen",
    "Putbacks",
    "Misc",
]

_SYNERGY_ENTITY_TYPES = ["P", "T"]  # Player, Team
_SYNERGY_GROUPINGS = ["offensive", "defensive"]
_UNSUPPORTED_INVALID_PARAMETER_COMBOS = frozenset(
    ("Putbacks", entity_type, grouping)
    for entity_type in _SYNERGY_ENTITY_TYPES
    for grouping in _SYNERGY_GROUPINGS
)


@registry.register
class SynergyPlayTypesExtractor(BaseExtractor):
    endpoint_name = "synergy_play_types"
    category = "synergy"

    def _fetch_synergy_frame(
        self,
        *,
        season: str,
        season_type: str,
        play_type: str,
        entity_type: str,
        grouping: str,
    ) -> pl.DataFrame:
        request_kwargs: dict[str, Any] = {
            "season": season,
            "play_type_nullable": play_type,
            "player_or_team_abbreviation": entity_type,
            "season_type_all_star": season_type,
            "type_grouping_nullable": grouping,
        }
        combo = (play_type, entity_type, grouping)
        if combo in _UNSUPPORTED_INVALID_PARAMETER_COMBOS:
            logger.debug(
                "synergy {}/{}/{} for {} ({}) is contract-blocked; skipping",
                play_type,
                entity_type,
                grouping,
                season,
                season_type,
            )
            return pl.DataFrame()
        return self._from_nba_api(SynergyPlayTypes, **request_kwargs)

    async def extract(self, **params: Any) -> pl.DataFrame:
        import polars as pl

        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        frames: list[pl.DataFrame] = []

        for play_type in _SYNERGY_PLAY_TYPES:
            for entity_type in _SYNERGY_ENTITY_TYPES:
                for grouping in _SYNERGY_GROUPINGS:
                    logger.debug(
                        "Extracting synergy {}/{}/{} for {} ({})",
                        play_type,
                        entity_type,
                        grouping,
                        season,
                        season_type,
                    )
                    df = self._fetch_synergy_frame(
                        season=season,
                        season_type=season_type,
                        play_type=play_type,
                        entity_type=entity_type,
                        grouping=grouping,
                    )
                    if not df.is_empty():
                        if "play_type" not in df.columns:
                            df = df.with_columns(pl.lit(play_type).alias("play_type"))
                        if "entity_type" not in df.columns:
                            df = df.with_columns(pl.lit(entity_type).alias("entity_type"))
                        if "type_grouping" not in df.columns:
                            df = df.with_columns(pl.lit(grouping).alias("type_grouping"))
                        frames.append(df)

        total = len(_SYNERGY_PLAY_TYPES) * len(_SYNERGY_ENTITY_TYPES) * len(_SYNERGY_GROUPINGS)
        if not frames:
            logger.info(
                "synergy_play_types for {} ({}) returned no rows across all {} combinations",
                season,
                season_type,
                total,
            )
            return pl.DataFrame()
        return pl.concat(frames, how="diagonal_relaxed")
