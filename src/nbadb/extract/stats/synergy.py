from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import SynergyPlayTypes

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl

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


@registry.register
class SynergyPlayTypesExtractor(BaseExtractor):
    endpoint_name = "synergy_play_types"
    category = "synergy"

    async def extract(self, **params: Any) -> pl.DataFrame:
        import polars as pl

        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        frames: list[pl.DataFrame] = []

        for play_type in _SYNERGY_PLAY_TYPES:
            for entity_type in _SYNERGY_ENTITY_TYPES:
                for grouping in _SYNERGY_GROUPINGS:
                    logger.debug(
                        "Extracting synergy {}/{}/{} for {}",
                        play_type,
                        entity_type,
                        grouping,
                        season,
                    )
                    try:
                        df = self._from_nba_api(
                            SynergyPlayTypes,
                            season=season,
                            play_type_nullable=play_type,
                            player_or_team_abbreviation=entity_type,
                            season_type_all_star=season_type,
                            type_grouping_nullable=grouping,
                        )
                        if not df.is_empty():
                            if "play_type" not in df.columns:
                                df = df.with_columns(pl.lit(play_type).alias("play_type"))
                            if "entity_type" not in df.columns:
                                df = df.with_columns(pl.lit(entity_type).alias("entity_type"))
                            if "type_grouping" not in df.columns:
                                df = df.with_columns(pl.lit(grouping).alias("type_grouping"))
                            frames.append(df)
                    except Exception as exc:
                        logger.warning(
                            "synergy {}/{}/{} for {} failed: {}",
                            play_type,
                            entity_type,
                            grouping,
                            season,
                            type(exc).__name__,
                        )
                    finally:
                        # Throttle within the 44-call loop to respect rate limits
                        time.sleep(0.6)

        total = len(_SYNERGY_PLAY_TYPES) * len(_SYNERGY_ENTITY_TYPES) * len(_SYNERGY_GROUPINGS)
        if not frames:
            raise RuntimeError(f"all {total} synergy combinations failed for {season}")
        return pl.concat(frames, how="diagonal_relaxed")
