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
from nba_api.stats.endpoints._base import Endpoint
from nba_api.stats.endpoints.videoeventsasset import VideoEventsAsset
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.core.types import (
    NBA_API_VIDEO_CONTEXT_MEASURE_VERSION,
    VIDEO_CONTEXT_MEASURE_PROVENANCE,
    VIDEO_SEASON_TYPE_PROVENANCE,
    SeasonType,
    VideoContextMeasure,
)
from nbadb.extract.base import BaseExtractor, _safe_from_pandas, _to_snake_case
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


_VIDEO_PROVENANCE_SCHEMA = pl.Schema(
    {
        "result_set_name": pl.String,
        "result_set_index": pl.Int64,
        "context_measure": pl.String,
        "context_measure_provenance": pl.String,
        "season_type_provenance": pl.String,
        "nba_api_contract_version": pl.String,
        "request_player_id": pl.Int64,
        "request_team_id": pl.Int64,
        "request_season": pl.String,
        "request_season_type": pl.String,
    }
)


def _unique_snake_case_columns(columns: list[str]) -> dict[str, str]:
    used: set[str] = set()
    rename_map: dict[str, str] = {}
    for column in columns:
        base_name = _to_snake_case(str(column))
        candidate = base_name
        suffix = 2
        while candidate in used:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        rename_map[column] = candidate
        used.add(candidate)
    return rename_map


def _preserve_provenance_columns(df: pl.DataFrame) -> pl.DataFrame:
    rename_map: dict[str, str] = {}
    occupied = set(df.columns)
    for column in _VIDEO_PROVENANCE_SCHEMA:
        if column not in occupied:
            continue
        candidate = f"upstream_{column}"
        while candidate in occupied:
            candidate = f"upstream_{candidate}"
        rename_map[column] = candidate
        occupied.add(candidate)
    return df.rename(rename_map) if rename_map else df


def _standard_video_result_set(payload: dict[Any, Any]) -> pl.DataFrame | None:
    headers = payload.get("headers")
    rows = payload.get("rowSet", payload.get("data"))
    if not isinstance(headers, list) or not isinstance(rows, list):
        return None
    pdf = Endpoint.DataSet(data={"headers": headers, "data": rows}).get_data_frame()
    return _safe_from_pandas(pdf)


def _dynamic_video_result_set(payload: object) -> pl.DataFrame | None:
    if isinstance(payload, dict):
        if not payload or any(isinstance(value, dict | list) for value in payload.values()):
            return None
        return pl.DataFrame([payload])
    if not isinstance(payload, list):
        return pl.DataFrame({"value": [payload]})
    if not payload:
        return pl.DataFrame()
    if all(isinstance(row, dict) for row in payload):
        return pl.DataFrame(payload)
    if all(isinstance(row, list | tuple) for row in payload):
        rows: list[list[object]] = []
        for row in payload:
            assert isinstance(row, list | tuple)
            rows.append(list(row))
        width = max(len(row) for row in rows)
        columns = [f"value_{index}" for index in range(width)]
        padded_rows = [row + [None] * (width - len(row)) for row in rows]
        return pl.DataFrame(padded_rows, schema=columns, orient="row")
    return pl.DataFrame({"value": payload}, strict=False)


def _video_result_set_frames(payload: dict[str, Any]) -> list[tuple[str, pl.DataFrame]]:
    root = payload.get("resultSets", payload.get("resultSet", payload))

    frames: list[tuple[str, pl.DataFrame]] = []

    def _collect(node: object, path: str) -> None:
        if isinstance(node, dict):
            standard = _standard_video_result_set(node)
            if standard is not None:
                name = str(node.get("name") or path or "result_set")
                frames.append((name, standard))
                return

            nested = {
                str(key): value for key, value in node.items() if isinstance(value, dict | list)
            }
            scalar = {key: value for key, value in node.items() if key not in nested}
            if scalar:
                frames.append((path or "result_set", pl.DataFrame([scalar])))
            for name, value in nested.items():
                child_path = f"{path}.{name}" if path else name
                _collect(value, child_path)
            return

        if (
            isinstance(node, list)
            and node
            and all(
                isinstance(item, dict)
                and "name" in item
                and isinstance(item.get("headers"), list)
                and isinstance(item.get("rowSet", item.get("data")), list)
                for item in node
            )
        ):
            for item in node:
                _collect(item, path)
            return

        frame = _dynamic_video_result_set(node)
        if frame is not None:
            frames.append((path or "result_set", frame))

    _collect(root, "")
    return frames


def _extract_video_result_sets(
    extractor: BaseExtractor,
    endpoint_cls: type,
    *,
    player_id: int,
    team_id: int,
    season: str,
    season_type: str,
    context_measure: str,
) -> pl.DataFrame:
    measure = VideoContextMeasure(context_measure)
    resolved_measure = measure.value
    resolved_season_type = SeasonType(season_type)
    request_kwargs: dict[str, Any] = {
        "player_id": player_id,
        "team_id": team_id,
        "season": season,
        "season_type_all_star": season_type,
        "context_measure_detailed": resolved_measure,
    }
    extractor._inject_timeout(request_kwargs)
    endpoint = endpoint_cls(get_request=False, **request_kwargs)
    response = NBAStatsHTTP().send_api_request(
        endpoint=endpoint.endpoint,
        parameters=endpoint.parameters,
        proxy=endpoint.proxy,
        headers=endpoint.headers,
        timeout=endpoint.timeout,
    )
    data_sets = _video_result_set_frames(response.get_dict())
    if not data_sets:
        logger.warning("{}: no dynamic result sets returned", extractor.endpoint_name)
        return pl.DataFrame(schema=_VIDEO_PROVENANCE_SCHEMA)

    frames: list[pl.DataFrame] = []
    for result_set_index, (result_set_name, df) in enumerate(data_sets):
        if df.width == 0:
            continue
        if df.columns:
            df = df.rename(_unique_snake_case_columns(list(df.columns)))
        df = _preserve_provenance_columns(df).with_columns(
            pl.lit(result_set_name).alias("result_set_name"),
            pl.lit(result_set_index, dtype=pl.Int64).alias("result_set_index"),
            pl.lit(resolved_measure).alias("context_measure"),
            pl.lit(",".join(VIDEO_CONTEXT_MEASURE_PROVENANCE[measure])).alias(
                "context_measure_provenance"
            ),
            pl.lit(",".join(VIDEO_SEASON_TYPE_PROVENANCE[resolved_season_type])).alias(
                "season_type_provenance"
            ),
            pl.lit(NBA_API_VIDEO_CONTEXT_MEASURE_VERSION).alias("nba_api_contract_version"),
            pl.lit(player_id, dtype=pl.Int64).alias("request_player_id"),
            pl.lit(team_id, dtype=pl.Int64).alias("request_team_id"),
            pl.lit(season).alias("request_season"),
            pl.lit(season_type).alias("request_season_type"),
        )
        frames.append(df)

    if not frames:
        return pl.DataFrame(schema=_VIDEO_PROVENANCE_SCHEMA)
    combined = pl.concat(frames, how="diagonal_relaxed")
    return extractor._validate(combined)


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
        return self._from_nba_api(VideoEvents, game_id=game_id)


@registry.register
class VideoEventsAssetExtractor(BaseExtractor):
    endpoint_name = "video_events_asset"
    category = "misc"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(VideoEventsAsset, game_id=game_id)


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
        return _extract_video_result_sets(
            self,
            VideoDetails,
            player_id=player_id,
            team_id=team_id,
            season=season,
            season_type=season_type,
            context_measure=context_measure,
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
        return _extract_video_result_sets(
            self,
            VideoDetailsAsset,
            player_id=player_id,
            team_id=team_id,
            season=season,
            season_type=season_type,
            context_measure=context_measure,
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
