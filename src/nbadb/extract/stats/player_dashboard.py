from __future__ import annotations

from typing import Any

import polars as pl
from nba_api.stats.endpoints import (
    PlayerDashboardByClutch,
    PlayerDashboardByGameSplits,
    PlayerDashboardByGeneralSplits,
    PlayerDashboardByLastNGames,
    PlayerDashboardByShootingSplits,
    PlayerDashboardByTeamPerformance,
    PlayerDashboardByYearOverYear,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry
from nbadb.orchestrate.seasons import current_season


def _attach_player_dashboard_context(
    df: pl.DataFrame,
    *,
    player_id: int,
    season: str,
    season_type: str,
) -> pl.DataFrame:
    additions: list[pl.Expr] = []
    if "player_id" not in df.columns:
        additions.append(pl.lit(player_id).alias("player_id"))
    if "season_year" not in df.columns:
        additions.append(pl.lit(season).alias("season_year"))
    if "season_type" not in df.columns:
        additions.append(pl.lit(season_type).alias("season_type"))
    return df.with_columns(additions) if additions else df


def _extract_dashboard_frame(
    extractor: BaseExtractor,
    endpoint_cls: type,
    *,
    player_id: int,
    season: str,
    season_type: str,
    season_type_kw: str,
) -> pl.DataFrame:
    df = extractor._from_nba_api(
        endpoint_cls,
        player_id=player_id,
        season=season,
        **{season_type_kw: season_type},
    )
    return _attach_player_dashboard_context(
        df,
        player_id=player_id,
        season=season,
        season_type=season_type,
    )


def _extract_dashboard_frames(
    extractor: BaseExtractor,
    endpoint_cls: type,
    *,
    player_id: int,
    season: str,
    season_type: str,
    season_type_kw: str,
) -> list[pl.DataFrame]:
    dfs = extractor._from_nba_api_multi(
        endpoint_cls,
        player_id=player_id,
        season=season,
        **{season_type_kw: season_type},
    )
    return [
        _attach_player_dashboard_context(
            df,
            player_id=player_id,
            season=season,
            season_type=season_type,
        )
        for df in dfs
    ]


@registry.register
class PlayerDashboardByYearOverYearExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_year_over_year"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByYearOverYear,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByYearOverYear,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )


@registry.register
class PlayerDashboardByLastNGamesExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_last_n_games"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByLastNGames,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByLastNGames,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )


@registry.register
class PlayerDashboardByGameSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_game_splits"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByGameSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByGameSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )


@registry.register
class PlayerDashboardByClutchExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_clutch"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByClutch,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByClutch,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )


@registry.register
class PlayerDashboardByShootingSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_shooting_splits"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByShootingSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByShootingSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )


@registry.register
class PlayerDashboardByTeamPerformanceExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_team_performance"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByTeamPerformance,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByTeamPerformance,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )


@registry.register
class PlayerDashboardGeneralSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_general_splits"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByGeneralSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByGeneralSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_all_star",
        )


# ── Aliased extractors with canonical short endpoint_names ───────────────────


@registry.register
class PlayerDashGameSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dash_game_splits"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByGameSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByGameSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )


@registry.register
class PlayerDashGeneralSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dash_general_splits"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByGeneralSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByGeneralSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )


@registry.register
class PlayerDashLastNGamesExtractor(BaseExtractor):
    endpoint_name = "player_dash_last_n_games"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByLastNGames,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByLastNGames,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )


@registry.register
class PlayerDashShootingSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dash_shooting_splits"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByShootingSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByShootingSplits,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )


@registry.register
class PlayerDashTeamPerfExtractor(BaseExtractor):
    endpoint_name = "player_dash_team_perf"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByTeamPerformance,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByTeamPerformance,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )


@registry.register
class PlayerDashYoyExtractor(BaseExtractor):
    endpoint_name = "player_dash_yoy"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frame(
            self,
            PlayerDashboardByYearOverYear,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return _extract_dashboard_frames(
            self,
            PlayerDashboardByYearOverYear,
            player_id=player_id,
            season=season,
            season_type=season_type,
            season_type_kw="season_type_playoffs",
        )
