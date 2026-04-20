from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import ScheduleLeagueV2
from nba_api.stats.endpoints.scheduleleaguev2int import ScheduleLeagueV2Int
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


def _schedule_int_payload_to_frames(payload: dict[str, Any]) -> list[pl.DataFrame]:
    import polars as pl

    league_schedule = payload.get("leagueSchedule")
    if not isinstance(league_schedule, dict):
        raise KeyError("leagueSchedule")

    season_year = league_schedule.get("seasonYear")
    league_id = league_schedule.get("leagueId")

    game_rows: list[dict[str, Any]] = []
    for game_date_block in league_schedule.get("gameDates", []):
        if not isinstance(game_date_block, dict):
            continue
        game_date = game_date_block.get("gameDate")
        for game in game_date_block.get("games", []):
            if not isinstance(game, dict):
                continue
            home_team = game.get("homeTeam") if isinstance(game.get("homeTeam"), dict) else {}
            away_team = game.get("awayTeam") if isinstance(game.get("awayTeam"), dict) else {}
            game_rows.append(
                {
                    "league_id": league_id,
                    "season_year": season_year,
                    "game_date": game_date,
                    "game_id": game.get("gameId"),
                    "game_code": game.get("gameCode"),
                    "game_status": game.get("gameStatus"),
                    "game_status_text": game.get("gameStatusText"),
                    "game_sequence": game.get("gameSequence"),
                    "game_date_est": game.get("gameDateEst"),
                    "game_time_est": game.get("gameTimeEst"),
                    "game_date_time_est": game.get("gameDateTimeEst"),
                    "game_date_utc": game.get("gameDateUTC"),
                    "game_time_utc": game.get("gameTimeUTC"),
                    "game_date_time_utc": game.get("gameDateTimeUTC"),
                    "away_team_time": game.get("awayTeamTime"),
                    "home_team_time": game.get("homeTeamTime"),
                    "day": game.get("day"),
                    "month_num": game.get("monthNum"),
                    "week_number": game.get("weekNumber"),
                    "week_name": game.get("weekName"),
                    "if_necessary": game.get("ifNecessary"),
                    "series_game_number": game.get("seriesGameNumber"),
                    "game_label": game.get("gameLabel"),
                    "game_sub_label": game.get("gameSubLabel"),
                    "series_text": game.get("seriesText"),
                    "arena_name": game.get("arenaName"),
                    "arena_state": game.get("arenaState"),
                    "arena_city": game.get("arenaCity"),
                    "postponed_status": game.get("postponedStatus"),
                    "branch_link": game.get("branchLink"),
                    "game_subtype": game.get("gameSubtype"),
                    "is_neutral": game.get("isNeutral"),
                    "home_team_team_id": home_team.get("teamId"),
                    "home_team_team_name": home_team.get("teamName"),
                    "home_team_team_city": home_team.get("teamCity"),
                    "home_team_team_tricode": home_team.get("teamTricode"),
                    "home_team_team_slug": home_team.get("teamSlug"),
                    "home_team_wins": home_team.get("wins"),
                    "home_team_losses": home_team.get("losses"),
                    "home_team_score": home_team.get("score"),
                    "home_team_seed": home_team.get("seed"),
                    "away_team_team_id": away_team.get("teamId"),
                    "away_team_team_name": away_team.get("teamName"),
                    "away_team_team_city": away_team.get("teamCity"),
                    "away_team_team_tricode": away_team.get("teamTricode"),
                    "away_team_team_slug": away_team.get("teamSlug"),
                    "away_team_wins": away_team.get("wins"),
                    "away_team_losses": away_team.get("losses"),
                    "away_team_score": away_team.get("score"),
                    "away_team_seed": away_team.get("seed"),
                }
            )

    week_rows: list[dict[str, Any]] = []
    for week in league_schedule.get("weeks", []):
        if not isinstance(week, dict):
            continue
        week_rows.append(
            {
                "league_id": league_id,
                "season_year": season_year,
                "week_number": week.get("weekNumber"),
                "week_name": week.get("weekName"),
                "start_date": week.get("startDate"),
                "end_date": week.get("endDate"),
            }
        )

    return [pl.from_dicts(game_rows), pl.from_dicts(week_rows)]


@registry.register
class ScheduleExtractor(BaseExtractor):
    endpoint_name = "schedule"
    category = "schedule"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        league_id: str = params.get("league_id", "00")
        logger.debug(f"Extracting schedule for {season}")
        return self._from_nba_api(ScheduleLeagueV2, season=season, league_id=league_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        season: str = params["season"]
        league_id: str = params.get("league_id", "00")
        return self._from_nba_api_multi(ScheduleLeagueV2, season=season, league_id=league_id)


@registry.register
class ScheduleIntExtractor(BaseExtractor):
    endpoint_name = "schedule_int"
    category = "schedule"

    @staticmethod
    def _is_schedule_int_shape_error(exc: Exception) -> bool:
        return isinstance(exc, ValueError) and "columns passed" in str(exc)

    def _fetch_schedule_int_payload(self, *, season: str, league_id: str) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {"season": season, "league_id": league_id}
        self._inject_timeout(request_kwargs)
        endpoint = ScheduleLeagueV2Int(get_request=False, **request_kwargs)
        return (
            NBAStatsHTTP()
            .send_api_request(
                endpoint=endpoint.endpoint,
                parameters=endpoint.parameters,
                proxy=endpoint.proxy,
                headers=endpoint.headers,
                timeout=endpoint.timeout,
            )
            .get_dict()
        )

    def _extract_all_with_fallback(self, *, season: str, league_id: str) -> list[pl.DataFrame]:
        try:
            return self._from_nba_api_multi(ScheduleLeagueV2Int, season=season, league_id=league_id)
        except Exception as exc:
            if not self._is_schedule_int_shape_error(exc):
                raise
        logger.warning(
            "schedule_int: falling back to raw leagueSchedule payload for {}",
            season,
        )
        payload = self._fetch_schedule_int_payload(season=season, league_id=league_id)
        return _schedule_int_payload_to_frames(payload)

    async def extract(self, **params: Any) -> pl.DataFrame:
        # Single-result fallback (returns SeasonGames only).
        # All staging entries use use_multi=True, so the orchestrator calls extract_all().
        season: str = params["season"]
        league_id: str = params.get("league_id", "00")
        logger.debug(f"Extracting international schedule for {season}")
        try:
            return self._from_nba_api(ScheduleLeagueV2Int, season=season, league_id=league_id)
        except Exception as exc:
            if not self._is_schedule_int_shape_error(exc):
                raise
        return self._extract_all_with_fallback(season=season, league_id=league_id)[0]

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        season: str = params["season"]
        league_id: str = params.get("league_id", "00")
        return self._extract_all_with_fallback(season=season, league_id=league_id)
