from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    CumeStatsPlayer,
    CumeStatsPlayerGames,
    CumeStatsTeam,
    CumeStatsTeamGames,
    DunkScoreLeaders,
    GLAlumBoxScoreSimilarityScore,
    GravityLeaders,
    LeagueGameFinder,
    TeamGameStreakFinder,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


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
        return self._from_nba_api(GLAlumBoxScoreSimilarityScore, **params)


@registry.register
class DunkScoreLeadersExtractor(BaseExtractor):
    endpoint_name = "dunk_score_leaders"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            DunkScoreLeaders,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class GravityLeadersExtractor(BaseExtractor):
    endpoint_name = "gravity_leaders"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            GravityLeaders,
            season=season,
            season_type_all_star=season_type,
        )
