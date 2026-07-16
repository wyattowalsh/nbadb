from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import polars as pl
from nba_api.live.nba.endpoints import BoxScore, Odds, PlayByPlay, ScoreBoard

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@dataclass(frozen=True, slots=True)
class LivePacketContract:
    upstream_endpoint: str
    attr: str
    source_endpoint: str
    natural_keys: tuple[str, ...]
    json_root: str
    staging_key: str
    star_tables: tuple[str, ...]
    typed_projections: tuple[tuple[str, str], ...] = ()

    @property
    def snapshot_spec(self) -> tuple[str, str, tuple[str, ...]]:
        return self.attr, self.source_endpoint, self.natural_keys


LIVE_PACKET_CONTRACTS = (
    LivePacketContract(
        "ScoreBoard",
        "games",
        "live_score_board",
        ("game_id",),
        "$.scoreboard.games",
        "stg_live_score_board",
        ("fact_live_score_board",),
    ),
    LivePacketContract(
        "Odds",
        "games",
        "live_odds",
        ("game_id",),
        "$.games",
        "stg_live_odds",
        ("fact_live_odds",),
    ),
    LivePacketContract(
        "PlayByPlay",
        "actions",
        "live_play_by_play",
        ("game_id", "action_number"),
        "$.game.actions",
        "stg_live_play_by_play",
        ("fact_live_play_by_play",),
    ),
    LivePacketContract(
        "BoxScore",
        "game_details",
        "live_box_score.game_details",
        ("game_id",),
        "$.game",
        "stg_live_box_score_game_details",
        ("fact_live_box_score_game",),
    ),
    LivePacketContract(
        "BoxScore",
        "arena",
        "live_box_score.arena",
        ("game_id",),
        "$.game.arena",
        "stg_live_box_score_arena",
        ("fact_live_box_score_arena",),
    ),
    LivePacketContract(
        "BoxScore",
        "officials",
        "live_box_score.officials",
        ("game_id", "person_id"),
        "$.game.officials",
        "stg_live_box_score_officials",
        ("bridge_live_box_score_official",),
    ),
    LivePacketContract(
        "BoxScore",
        "home_team_stats",
        "live_box_score.home_team_stats",
        ("game_id", "team_id"),
        "$.game.homeTeam",
        "stg_live_box_score_team_stats_home",
        ("fact_live_box_score_team",),
    ),
    LivePacketContract(
        "BoxScore",
        "away_team_stats",
        "live_box_score.away_team_stats",
        ("game_id", "team_id"),
        "$.game.awayTeam",
        "stg_live_box_score_team_stats_away",
        ("fact_live_box_score_team",),
    ),
    LivePacketContract(
        "BoxScore",
        "home_team_player_stats",
        "live_box_score.home_team_player_stats",
        ("game_id", "person_id"),
        "$.game.homeTeam.players",
        "stg_live_box_score_player_stats_home",
        ("fact_live_box_score_player",),
        (("statistics.points", "points"),),
    ),
    LivePacketContract(
        "BoxScore",
        "away_team_player_stats",
        "live_box_score.away_team_player_stats",
        ("game_id", "person_id"),
        "$.game.awayTeam.players",
        "stg_live_box_score_player_stats_away",
        ("fact_live_box_score_player",),
        (("statistics.points", "points"),),
    ),
)

LIVE_NON_ANALYTIC_JSON_ROOTS = {
    "BoxScore": ("$.meta",),
    "PlayByPlay": ("$.meta",),
    "ScoreBoard": ("$.meta",),
}

LIVE_RAW_ONLY_REFERENCE_JSON_PATHS = {
    "ScoreBoard": frozenset(
        {
            "$.scoreboard.gameDate",
            "$.scoreboard.leagueId",
            "$.scoreboard.leagueName",
        }
    )
}

LIVE_PARAMETER_FIELD_ROUTES = {
    ("PlayByPlay", "$.game.gameId"): {
        "source_endpoint": "live_play_by_play",
        "staging_key": "stg_live_play_by_play",
        "star_tables": ("fact_live_play_by_play",),
        "target_column": "game_id",
    }
}

_BOX_SCORE_PACKET_CONTRACTS = tuple(
    contract for contract in LIVE_PACKET_CONTRACTS if contract.upstream_endpoint == "BoxScore"
)
_PACKET_BY_SOURCE_ENDPOINT = {
    contract.source_endpoint: contract for contract in LIVE_PACKET_CONTRACTS
}
_SCOREBOARD_PACKET = _PACKET_BY_SOURCE_ENDPOINT["live_score_board"]
_ODDS_PACKET = _PACKET_BY_SOURCE_ENDPOINT["live_odds"]
_PLAY_BY_PLAY_PACKET = _PACKET_BY_SOURCE_ENDPOINT["live_play_by_play"]
_BOX_SCORE_PRIMARY_PACKET = _PACKET_BY_SOURCE_ENDPOINT["live_box_score.game_details"]
_BOX_SCORE_PACKETS = [contract.snapshot_spec for contract in _BOX_SCORE_PACKET_CONTRACTS]
_BOX_SCORE_FIELD_PROJECTIONS = {
    contract.source_endpoint: dict(contract.typed_projections)
    for contract in _BOX_SCORE_PACKET_CONTRACTS
    if contract.typed_projections
}


@registry.register
class LiveScoreBoardExtractor(BaseExtractor):
    endpoint_name = "live_score_board"
    category = "live"
    snapshot_grain = _SCOREBOARD_PACKET.natural_keys

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_live(
            ScoreBoard,
            _SCOREBOARD_PACKET.attr,
            source_endpoint=_SCOREBOARD_PACKET.source_endpoint,
            natural_keys=_SCOREBOARD_PACKET.natural_keys,
            **params,
        )


@registry.register
class LiveOddsExtractor(BaseExtractor):
    endpoint_name = "live_odds"
    category = "live"
    snapshot_grain = _ODDS_PACKET.natural_keys

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_live(
            Odds,
            _ODDS_PACKET.attr,
            source_endpoint=_ODDS_PACKET.source_endpoint,
            natural_keys=_ODDS_PACKET.natural_keys,
            **params,
        )


@registry.register
class LivePlayByPlayExtractor(BaseExtractor):
    endpoint_name = "live_play_by_play"
    category = "live"
    snapshot_grain = _PLAY_BY_PLAY_PACKET.natural_keys

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_live(
            PlayByPlay,
            _PLAY_BY_PLAY_PACKET.attr,
            source_endpoint=_PLAY_BY_PLAY_PACKET.source_endpoint,
            natural_keys=_PLAY_BY_PLAY_PACKET.natural_keys,
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
            _BOX_SCORE_PRIMARY_PACKET.attr,
            source_endpoint=_BOX_SCORE_PRIMARY_PACKET.source_endpoint,
            natural_keys=_BOX_SCORE_PRIMARY_PACKET.natural_keys,
            **params,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_live_multi(
            BoxScore,
            _BOX_SCORE_PACKETS,
            field_projections_by_source=_BOX_SCORE_FIELD_PROJECTIONS,
            **params,
        )
