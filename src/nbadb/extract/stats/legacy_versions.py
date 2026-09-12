"""Physical legacy ``nba_api`` endpoint classes with distinct response contracts.

The modern wrappers remain the preferred modeled sources, but these classes are
separate provider surfaces with result sets and fields that must still reach the
landing sink.  They therefore get explicit extractor identities instead of being
silently treated as aliases of their V3 successors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from nba_api.stats.endpoints import (
    BoxScoreAdvancedV2,
    BoxScoreFourFactorsV2,
    BoxScoreMiscV2,
    BoxScoreScoringV2,
    BoxScoreTraditionalV2,
    BoxScoreUsageV2,
    LeagueStandings,
    PlayByPlay,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


class _LegacyGameMultiExtractor(BaseExtractor):
    endpoint_cls: ClassVar[type]

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(self.endpoint_cls, game_id=str(params["game_id"]))

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(self.endpoint_cls, game_id=str(params["game_id"]))


@registry.register
class BoxScoreTraditionalV2Extractor(_LegacyGameMultiExtractor):
    endpoint_name = "box_score_traditional_v2"
    category = "box_score"
    endpoint_cls = BoxScoreTraditionalV2

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(BoxScoreTraditionalV2, game_id=str(params["game_id"]))


@registry.register
class BoxScoreAdvancedV2Extractor(_LegacyGameMultiExtractor):
    endpoint_name = "box_score_advanced_v2"
    category = "box_score"
    endpoint_cls = BoxScoreAdvancedV2

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(BoxScoreAdvancedV2, game_id=str(params["game_id"]))


@registry.register
class BoxScoreMiscV2Extractor(_LegacyGameMultiExtractor):
    endpoint_name = "box_score_misc_v2"
    category = "box_score"
    endpoint_cls = BoxScoreMiscV2

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(BoxScoreMiscV2, game_id=str(params["game_id"]))


@registry.register
class BoxScoreScoringV2Extractor(_LegacyGameMultiExtractor):
    endpoint_name = "box_score_scoring_v2"
    category = "box_score"
    endpoint_cls = BoxScoreScoringV2

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(BoxScoreScoringV2, game_id=str(params["game_id"]))


@registry.register
class BoxScoreUsageV2Extractor(_LegacyGameMultiExtractor):
    endpoint_name = "box_score_usage_v2"
    category = "box_score"
    endpoint_cls = BoxScoreUsageV2

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(BoxScoreUsageV2, game_id=str(params["game_id"]))


@registry.register
class BoxScoreFourFactorsV2Extractor(_LegacyGameMultiExtractor):
    endpoint_name = "box_score_four_factors_v2"
    category = "box_score"
    endpoint_cls = BoxScoreFourFactorsV2

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(BoxScoreFourFactorsV2, game_id=str(params["game_id"]))


@registry.register
class PlayByPlayLegacyExtractor(_LegacyGameMultiExtractor):
    endpoint_name = "play_by_play_legacy"
    category = "play_by_play"
    endpoint_cls = PlayByPlay

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(PlayByPlay, game_id=str(params["game_id"]))


@registry.register
class LeagueStandingsLegacyExtractor(BaseExtractor):
    endpoint_name = "league_standings_legacy"
    category = "standings"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(
            LeagueStandings,
            league_id=str(params.get("league_id", "00")),
            season=str(params["season"]),
            season_type=str(params.get("season_type", "Regular Season")),
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(
            LeagueStandings,
            league_id=str(params.get("league_id", "00")),
            season=str(params["season"]),
            season_type=str(params.get("season_type", "Regular Season")),
        )
