from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from nbadb.extract.stats.legacy_versions import (
    BoxScoreAdvancedV2Extractor,
    BoxScoreFourFactorsV2Extractor,
    BoxScoreMiscV2Extractor,
    BoxScoreScoringV2Extractor,
    BoxScoreTraditionalV2Extractor,
    BoxScoreUsageV2Extractor,
    LeagueStandingsLegacyExtractor,
    PlayByPlayLegacyExtractor,
)

_GAME_EXTRACTORS = (
    (BoxScoreTraditionalV2Extractor, "BoxScoreTraditionalV2", 3),
    (BoxScoreAdvancedV2Extractor, "BoxScoreAdvancedV2", 2),
    (BoxScoreMiscV2Extractor, "BoxScoreMiscV2", 2),
    (BoxScoreScoringV2Extractor, "BoxScoreScoringV2", 2),
    (BoxScoreUsageV2Extractor, "BoxScoreUsageV2", 2),
    (BoxScoreFourFactorsV2Extractor, "BoxScoreFourFactorsV2", 2),
    (PlayByPlayLegacyExtractor, "PlayByPlay", 2),
)


@pytest.mark.parametrize("extractor_cls, endpoint_name, result_set_count", _GAME_EXTRACTORS)
@pytest.mark.asyncio
async def test_physical_game_endpoint_uses_exact_provider_class_and_all_result_sets(
    monkeypatch: pytest.MonkeyPatch,
    extractor_cls: type,
    endpoint_name: str,
    result_set_count: int,
) -> None:
    extractor = extractor_cls()
    captured: list[tuple[str, dict[str, object]]] = []

    def _multi(endpoint_cls: type, **kwargs: Any) -> list[pl.DataFrame]:
        endpoint = endpoint_cls(get_request=False, **kwargs)
        captured.append((endpoint_cls.__name__, dict(endpoint.parameters)))
        return [pl.DataFrame() for _ in endpoint_cls.expected_data]

    monkeypatch.setattr(extractor, "_from_nba_api_multi", _multi)

    frames = await extractor.extract_all(game_id="0022400001")

    assert len(frames) == result_set_count
    assert captured[0][0] == endpoint_name
    assert captured[0][1]["GameID"] == "0022400001"


@pytest.mark.asyncio
async def test_legacy_standings_preserves_explicit_league_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = LeagueStandingsLegacyExtractor()
    captured: dict[str, object] = {}

    def _multi(endpoint_cls: type, **kwargs: Any) -> list[pl.DataFrame]:
        captured.update(endpoint_cls(get_request=False, **kwargs).parameters)
        return [pl.DataFrame()]

    monkeypatch.setattr(extractor, "_from_nba_api_multi", _multi)

    frames = await extractor.extract_all(
        league_id="10",
        season="2024-25",
        season_type="Regular Season",
    )

    assert len(frames) == 1
    assert captured["LeagueID"] == "10"
    assert captured["Season"] == "2024-25"
    assert captured["SeasonType"] == "Regular Season"
