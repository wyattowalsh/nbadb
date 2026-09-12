from __future__ import annotations

from datetime import datetime
from typing import Any

import polars as pl
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
from nba_api.stats.endpoints.videoeventsasset import VideoEventsAsset

from nbadb.core.errors import ResponseContractError
from nbadb.core.types import (
    SeasonType,
    VideoContextMeasure,
)
from nbadb.extract.base import BaseExtractor, _to_snake_case
from nbadb.extract.registry import registry
from nbadb.orchestrate.cume_workload_contract import (
    CumeEntityKind,
    CumeWorkloadContractError,
    CumeWorkloadDisposition,
    CumeWorkloadValue,
)
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


def _extract_video_unknown_response(
    extractor: BaseExtractor,
    endpoint_cls: type,
    *,
    player_id: int,
    team_id: int,
    season: str,
    season_type: str,
    context_measure: str,
    league_id_nullable: str | None,
) -> pl.DataFrame:
    measure = VideoContextMeasure(context_measure)
    resolved_measure = measure.value
    _resolved_season_type = SeasonType(season_type)
    request_kwargs: dict[str, Any] = {
        "player_id": player_id,
        "team_id": team_id,
        "season": season,
        "season_type_all_star": season_type,
        "context_measure_detailed": resolved_measure,
    }
    if league_id_nullable is not None:
        request_kwargs["league_id_nullable"] = league_id_nullable
    payload = extractor._fetch_nba_api_payload(endpoint_cls, **request_kwargs)
    if payload.unknown_response is None:
        raise ResponseContractError("unknown-response endpoint omitted its retained observation")
    # No provider result inventory exists for these exact endpoints. The typed
    # observation retained by BaseExtractor is the authority; emitting dynamic
    # columns here would falsely turn observed JSON paths into provider schema.
    return pl.DataFrame()


def _video_league_id_nullable(params: dict[str, Any]) -> str | None:
    """Resolve an explicit logical competition without replacing provider omission."""

    present = tuple(
        (name, params[name]) for name in ("league_id", "league_id_nullable") if name in params
    )
    if not present:
        return None
    if any(type(value) is not str or not value or value != value.strip() for _, value in present):
        raise ResponseContractError(
            "video competition scope must be an exact nonempty league identifier"
        )
    league_id = present[0][1]
    if any(value != league_id for _, value in present[1:]):
        raise ResponseContractError("video competition scope aliases conflict")
    assert isinstance(league_id, str)
    return league_id


def _cume_request_params(
    params: dict[str, Any],
    *,
    entity_kind: CumeEntityKind,
) -> dict[str, int | str]:
    entity_key = f"{entity_kind.value}_id"
    workload_params = dict(params)
    if "snapshot_at" in workload_params:
        snapshot_at = workload_params.pop("snapshot_at")
        if (
            type(snapshot_at) is not datetime
            or snapshot_at.tzinfo is None
            or snapshot_at.utcoffset() is None
        ):
            raise CumeWorkloadContractError("snapshot_at must be an exact timezone-aware datetime")

    has_workload = "workload" in workload_params
    serialized_fields = frozenset(
        {
            entity_key,
            "season",
            "season_type",
            "game_ids",
            "cume_workload_sha256",
            "foundation_receipt_sha256",
            "provider_authority_sha256",
        }
    )
    if has_workload:
        typed_workload_fields = {"workload", entity_key, "season", "season_type"}
        unexpected_fields = set(workload_params) - typed_workload_fields
        if unexpected_fields & serialized_fields:
            raise CumeWorkloadContractError(
                "provide a typed workload or serialized workload fields, not both"
            )
        if unexpected_fields:
            raise CumeWorkloadContractError(
                "typed cume workload received unexpected transport fields"
            )
        supplied_workload = workload_params["workload"]
        if not isinstance(supplied_workload, CumeWorkloadValue):
            raise CumeWorkloadContractError("workload must be a CumeWorkloadValue")
        workload = CumeWorkloadValue.from_canonical_bytes(supplied_workload.canonical_bytes)
    else:
        if set(workload_params) != serialized_fields:
            raise CumeWorkloadContractError(
                "serialized cume workload requires exact scope, game, receipt, "
                "provider, and digest fields"
            )
        workload = CumeWorkloadValue.complete(
            entity_kind=entity_kind,
            entity_id=workload_params[entity_key],
            season=workload_params["season"],
            season_type=workload_params["season_type"],
            game_ids=workload_params["game_ids"],
            foundation_receipt_sha256=workload_params["foundation_receipt_sha256"],
            provider_authority_sha256=workload_params["provider_authority_sha256"],
        )
        if workload_params["cume_workload_sha256"] != workload.content_sha256:
            raise CumeWorkloadContractError(
                "serialized cume workload digest differs from its exact reconstructed workload"
            )

    if workload.entity_kind is not entity_kind:
        raise CumeWorkloadContractError("cume workload entity kind does not match extractor")
    if workload.disposition is CumeWorkloadDisposition.TYPED_ZERO:
        raise CumeWorkloadContractError("typed-zero cume workload is not executable")
    for key, expected in (
        (entity_key, workload.entity_id),
        ("season", workload.season),
        ("season_type", workload.season_type),
    ):
        if key in workload_params and workload_params[key] != expected:
            raise CumeWorkloadContractError(f"explicit {key} does not match cume workload")

    return {
        entity_key: workload.entity_id,
        "game_ids": workload.encoded_game_ids,
        "season": workload.season,
        "season_type_all_star": workload.season_type,
    }


@registry.register
class CumeStatsPlayerExtractor(BaseExtractor):
    endpoint_name = "cume_stats_player"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        request_params = _cume_request_params(params, entity_kind=CumeEntityKind.PLAYER)
        return self._from_nba_api(CumeStatsPlayer, **request_params)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        request_params = _cume_request_params(params, entity_kind=CumeEntityKind.PLAYER)
        return self._from_nba_api_multi(CumeStatsPlayer, **request_params)


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
        request_params = _cume_request_params(params, entity_kind=CumeEntityKind.TEAM)
        return self._from_nba_api(CumeStatsTeam, **request_params)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        request_params = _cume_request_params(params, entity_kind=CumeEntityKind.TEAM)
        return self._from_nba_api_multi(CumeStatsTeam, **request_params)


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
        api_params = dict(params)
        for alias, nba_api_name in (
            ("team_id", "team_id_nullable"),
            ("season", "season_nullable"),
            ("season_type", "season_type_nullable"),
        ):
            if alias in api_params:
                value = api_params.pop(alias)
                api_params.setdefault(nba_api_name, value)
        return self._from_nba_api(TeamGameStreakFinder, **api_params)


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
        payload = self._fetch_nba_api_payload(DunkScoreLeaders, **request_kwargs)

        rows = payload.get("dunks")
        if not isinstance(rows, list):
            raise KeyError("dunks")
        df = _payload_rows_to_frame(rows)
        return df if df.is_empty() else self._validate(df)


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
        payload = self._fetch_nba_api_payload(GravityLeaders, **request_kwargs)

        rows = payload.get("leaders")
        if not isinstance(rows, list):
            raise KeyError("leaders")
        df = _payload_rows_to_frame(rows)
        return df if df.is_empty() else self._validate(df)


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
        game_event_id = params["game_event_id"]
        return self._from_nba_api(
            VideoEvents,
            game_id=game_id,
            game_event_id=game_event_id,
        )


@registry.register
class VideoEventsAssetExtractor(BaseExtractor):
    endpoint_name = "video_events_asset"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        game_event_id = params["game_event_id"]
        return self._from_nba_api(
            VideoEventsAsset,
            game_id=game_id,
            game_event_id=game_event_id,
        )


@registry.register
class VideoDetailsExtractor(BaseExtractor):
    endpoint_name = "video_details"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        team_id: int = params["team_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        context_measure = str(params.get("context_measure", VideoContextMeasure.PTS.value))
        league_id_nullable = _video_league_id_nullable(params)
        return _extract_video_unknown_response(
            self,
            VideoDetails,
            player_id=player_id,
            team_id=team_id,
            season=season,
            season_type=season_type,
            context_measure=context_measure,
            league_id_nullable=league_id_nullable,
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
        context_measure = str(params.get("context_measure", VideoContextMeasure.PTS.value))
        league_id_nullable = _video_league_id_nullable(params)
        return _extract_video_unknown_response(
            self,
            VideoDetailsAsset,
            player_id=player_id,
            team_id=team_id,
            season=season,
            season_type=season_type,
            context_measure=context_measure,
            league_id_nullable=league_id_nullable,
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
