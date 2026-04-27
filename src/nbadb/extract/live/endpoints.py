from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl
from nba_api.live.nba.endpoints import BoxScore, Odds, PlayByPlay, ScoreBoard

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

_SCOREBOARD_GRAIN = ("game_id",)
_ODDS_GRAIN = ("game_id",)
_PLAY_BY_PLAY_GRAIN = ("game_id", "action_number")
_BOX_SCORE_PACKETS: list[tuple[str, str, tuple[str, ...]]] = [
    ("game_details", "live_box_score.game_details", ("game_id",)),
    ("arena", "live_box_score.arena", ("game_id",)),
    ("officials", "live_box_score.officials", ("game_id", "person_id")),
    ("home_team_stats", "live_box_score.home_team_stats", ("game_id", "team_id")),
    ("away_team_stats", "live_box_score.away_team_stats", ("game_id", "team_id")),
    (
        "home_team_player_stats",
        "live_box_score.home_team_player_stats",
        ("game_id", "person_id"),
    ),
    (
        "away_team_player_stats",
        "live_box_score.away_team_player_stats",
        ("game_id", "person_id"),
    ),
]


@registry.register
class LiveScoreBoardExtractor(BaseExtractor):
    endpoint_name = "live_score_board"
    category = "live"
    snapshot_grain = _SCOREBOARD_GRAIN

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_live(
            ScoreBoard,
            "games",
            source_endpoint=self.endpoint_name,
            natural_keys=_SCOREBOARD_GRAIN,
            **params,
        )


@registry.register
class LiveOddsExtractor(BaseExtractor):
    endpoint_name = "live_odds"
    category = "live"
    snapshot_grain = _ODDS_GRAIN

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_live(
            Odds,
            "games",
            source_endpoint=self.endpoint_name,
            natural_keys=_ODDS_GRAIN,
            **params,
        )


@registry.register
class LivePlayByPlayExtractor(BaseExtractor):
    endpoint_name = "live_play_by_play"
    category = "live"
    snapshot_grain = _PLAY_BY_PLAY_GRAIN

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_live(
            PlayByPlay,
            "actions",
            source_endpoint=self.endpoint_name,
            natural_keys=_PLAY_BY_PLAY_GRAIN,
            **params,
        )


@registry.register
class LiveBoxScoreExtractor(BaseExtractor):
    endpoint_name = "live_box_score"
    category = "live"
    snapshot_packets = _BOX_SCORE_PACKETS

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_live(
            BoxScore,
            "game_details",
            source_endpoint="live_box_score.game_details",
            natural_keys=("game_id",),
            **params,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_live_multi(BoxScore, _BOX_SCORE_PACKETS, **params)
