from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger
from nba_api.stats.endpoints import (
    BoxScoreMatchupsV3,
    LeagueDashLineups,
    LeagueSeasonMatchups,
    MatchupsRollup,
    TeamDashLineups,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


def _parse_matchup_minutes(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    parts = text.split(":")
    try:
        if len(parts) == 2:
            minutes, seconds = parts
            return float(minutes) + float(seconds) / 60
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return float(hours) * 60 + float(minutes) + float(seconds) / 60
        return float(text)
    except ValueError:
        return None


@registry.register
class BoxScoreMatchupsExtractor(BaseExtractor):
    endpoint_name = "box_score_matchups"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        logger.debug(f"Extracting matchups for {game_id}")
        return self._from_nba_api(BoxScoreMatchupsV3, game_id=game_id)


@registry.register
class LeagueSeasonMatchupsExtractor(BaseExtractor):
    endpoint_name = "league_season_matchups"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        converted = self._call_nba_api(
            LeagueSeasonMatchups,
            season=season,
            season_type_playoffs=season_type,
        )
        if not converted:
            logger.warning(f"{self.endpoint_name}: no data frames returned")
            return pl.DataFrame()

        df = converted[0]
        if "matchup_min" in df.columns:
            df = df.with_columns(
                pl.col("matchup_min")
                .map_elements(_parse_matchup_minutes, return_dtype=pl.Float64)
                .alias("matchup_min")
            )
        return self._validate(df)


@registry.register
class MatchupsRollupExtractor(BaseExtractor):
    endpoint_name = "matchups_rollup"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            MatchupsRollup,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class LeagueDashLineupsExtractor(BaseExtractor):
    endpoint_name = "league_dash_lineups"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        group_quantity: int = params.get("group_quantity", 5)
        return self._from_nba_api(
            LeagueDashLineups,
            season=season,
            season_type_all_star=season_type,
            group_quantity=group_quantity,
        )


@registry.register
class TeamDashLineupsExtractor(BaseExtractor):
    endpoint_name = "team_dash_lineups"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        group_quantity: int = params.get("group_quantity", 5)
        return self._from_nba_api(
            TeamDashLineups,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
            group_quantity=group_quantity,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        group_quantity: int = params.get("group_quantity", 5)
        return self._from_nba_api_multi(
            TeamDashLineups,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
            group_quantity=group_quantity,
        )
