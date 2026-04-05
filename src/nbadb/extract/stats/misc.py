from __future__ import annotations

import json
from typing import Any

import polars as pl
from loguru import logger
from nba_api.stats.endpoints import (
    CumeStatsPlayer,
    CumeStatsPlayerGames,
    CumeStatsTeam,
    CumeStatsTeamGames,
    DunkScoreLeaders,
    FantasyWidget,
    GLAlumBoxScoreSimilarityScore,
    GravityLeaders,
    InfographicFanDuelPlayer,
    LeagueGameFinder,
    PlayerFantasyProfileBarGraph,
    TeamGameStreakFinder,
    VideoDetails,
    VideoDetailsAsset,
    VideoEvents,
    VideoStatus,
)
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.extract.base import BaseExtractor, _to_snake_case
from nbadb.extract.registry import registry
from nbadb.orchestrate.seasons import current_season


def _season_start_year(season: str | int | None) -> int:
    if isinstance(season, int):
        return season
    if isinstance(season, str) and season:
        return int(season.split("-", 1)[0])
    return int(current_season().split("-", 1)[0])


def _payload_rows_to_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    df = pl.DataFrame(rows)
    if df.columns:
        df = df.rename({c: _to_snake_case(c) for c in df.columns})
    return df


def _response_text(response: Any) -> str:
    raw = response.get_response()
    if isinstance(raw, str):
        return raw
    return getattr(raw, "text", str(raw))


def _is_unavailable_response(text: str) -> bool:
    normalized = text.strip()
    return (
        not normalized or "(403) Forbidden" in normalized or "System.Net.WebException" in normalized
    )


@registry.register
class CumeStatsPlayerExtractor(BaseExtractor):
    endpoint_name = "cume_stats_player"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            CumeStatsPlayer,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            CumeStatsPlayer,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class CumeStatsPlayerGamesExtractor(BaseExtractor):
    endpoint_name = "cume_stats_player_games"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            CumeStatsPlayerGames,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class CumeStatsTeamExtractor(BaseExtractor):
    endpoint_name = "cume_stats_team"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            CumeStatsTeam,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            CumeStatsTeam,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class CumeStatsTeamGamesExtractor(BaseExtractor):
    endpoint_name = "cume_stats_team_games"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            CumeStatsTeamGames,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueGameFinderExtractor(BaseExtractor):
    endpoint_name = "league_game_finder"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(LeagueGameFinder, **params)


@registry.register
class TeamGameStreakFinderExtractor(BaseExtractor):
    endpoint_name = "team_game_streak_finder"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(TeamGameStreakFinder, **params)


@registry.register
class GLAlumBoxScoreSimilarityScoreExtractor(BaseExtractor):
    endpoint_name = "gl_alum_box_score_similarity_score"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        person1_id = params.get("person1_id", params.get("player_id"))
        if person1_id is None:
            raise KeyError("person1_id")

        person2_id = params.get("person2_id", params.get("comparison_player_id", person1_id))
        season_year = _season_start_year(params.get("season"))
        season_type = params.get("season_type", "Regular Season")
        league_id = params.get("league_id", "00")
        return self._from_nba_api(
            GLAlumBoxScoreSimilarityScore,
            person1_id=person1_id,
            person2_id=person2_id,
            person1_league_id=params.get("person1_league_id", league_id),
            person1_season_year=params.get("person1_season_year", season_year),
            person1_season_type=params.get("person1_season_type", season_type),
            person2_league_id=params.get("person2_league_id", league_id),
            person2_season_year=params.get("person2_season_year", season_year),
            person2_season_type=params.get("person2_season_type", season_type),
        )


@registry.register
class DunkScoreLeadersExtractor(BaseExtractor):
    endpoint_name = "dunk_score_leaders"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        request_kwargs: dict[str, Any] = {
            "season": season,
            "season_type_all_star": season_type,
            "player_id_nullable": "0",
            "team_id_nullable": "0",
        }
        self._inject_timeout(request_kwargs)
        endpoint = DunkScoreLeaders(get_request=False, **request_kwargs)
        response = NBAStatsHTTP().send_api_request(
            endpoint=endpoint.endpoint,
            parameters=endpoint.parameters,
            proxy=endpoint.proxy,
            headers=endpoint.headers,
            timeout=endpoint.timeout,
        )
        try:
            payload = response.get_dict()
        except json.JSONDecodeError:
            if _is_unavailable_response(_response_text(response)):
                logger.info(
                    "dunk_score_leaders unavailable for {} ({}); returning empty frame",
                    season,
                    season_type,
                )
                return pl.DataFrame()
            raise

        rows = payload.get("dunks")
        if not isinstance(rows, list):
            raise KeyError("dunks")
        return _payload_rows_to_frame(rows)


@registry.register
class GravityLeadersExtractor(BaseExtractor):
    endpoint_name = "gravity_leaders"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        request_kwargs: dict[str, Any] = {
            "season": season,
            "season_type_all_star": season_type,
        }
        self._inject_timeout(request_kwargs)
        endpoint = GravityLeaders(get_request=False, **request_kwargs)
        response = NBAStatsHTTP().send_api_request(
            endpoint=endpoint.endpoint,
            parameters=endpoint.parameters,
            proxy=endpoint.proxy,
            headers=endpoint.headers,
            timeout=endpoint.timeout,
        )
        try:
            payload = response.get_dict()
        except json.JSONDecodeError:
            if _is_unavailable_response(_response_text(response)):
                logger.info(
                    "gravity_leaders unavailable for {} ({}); returning empty frame",
                    season,
                    season_type,
                )
                return pl.DataFrame()
            raise

        rows = payload.get("leaders")
        if not isinstance(rows, list):
            raise KeyError("leaders")
        return _payload_rows_to_frame(rows)


@registry.register
class InfographicFanDuelPlayerExtractor(BaseExtractor):
    endpoint_name = "infographic_fanduel_player"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(InfographicFanDuelPlayer, game_id=game_id)


@registry.register
class VideoStatusExtractor(BaseExtractor):
    endpoint_name = "video_status"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_date: str = params["game_date"]
        league_id: str = params.get("league_id", "00")
        return self._from_nba_api(
            VideoStatus,
            game_date=game_date,
            league_id=league_id,
        )


@registry.register
class VideoEventsExtractor(BaseExtractor):
    endpoint_name = "video_events"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(VideoEvents, game_id=game_id)


@registry.register
class VideoDetailsExtractor(BaseExtractor):
    endpoint_name = "video_details"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        team_id: int = params["team_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            VideoDetails,
            player_id=player_id,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class VideoDetailsAssetExtractor(BaseExtractor):
    endpoint_name = "video_details_asset"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        team_id: int = params["team_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            VideoDetailsAsset,
            player_id=player_id,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class FantasyWidgetExtractor(BaseExtractor):
    endpoint_name = "fantasy_widget"
    category = "league_stats"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            FantasyWidget,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerFantasyProfileBarGraphExtractor(BaseExtractor):
    endpoint_name = "player_fantasy_profile"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "")
        return self._from_nba_api(
            PlayerFantasyProfileBarGraph,
            player_id=player_id,
            season=season,
            season_type_all_star_nullable=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "")
        return self._from_nba_api_multi(
            PlayerFantasyProfileBarGraph,
            player_id=player_id,
            season=season,
            season_type_all_star_nullable=season_type,
        )
