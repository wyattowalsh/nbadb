from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl
from nba_api.live.nba.endpoints import BoxScore, Odds, PlayByPlay, ScoreBoard

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

_BOX_SCORE_ATTRS = [
    "game_details",
    "arena",
    "officials",
    "home_team_stats",
    "away_team_stats",
    "home_team_player_stats",
    "away_team_player_stats",
]


@registry.register
class LiveScoreBoardExtractor(BaseExtractor):
    endpoint_name = "live_score_board"
    category = "live"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_live(ScoreBoard, "games")


@registry.register
class LiveOddsExtractor(BaseExtractor):
    endpoint_name = "live_odds"
    category = "live"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_live(Odds, "games")


@registry.register
class LivePlayByPlayExtractor(BaseExtractor):
    endpoint_name = "live_play_by_play"
    category = "live"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_live(PlayByPlay, "actions", game_id=game_id)


@registry.register
class LiveBoxScoreExtractor(BaseExtractor):
    endpoint_name = "live_box_score"
    category = "live"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_live(BoxScore, "game_details", game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_live_multi(BoxScore, _BOX_SCORE_ATTRS, game_id=game_id)
