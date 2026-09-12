from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from nbadb.extract.stats.player_compare import TeamAndPlayersVsPlayersExtractor

_PARAMS: dict[str, object] = {
    "team_id": 1610612737,
    "vs_team_id": 1610612738,
    "player_id1": 101,
    "player_id2": 102,
    "player_id3": 103,
    "player_id4": 104,
    "player_id5": 105,
    "vs_player_id1": 201,
    "vs_player_id2": 202,
    "vs_player_id3": 203,
    "vs_player_id4": 204,
    "vs_player_id5": 205,
    "season": "2024-25",
    "season_type": "Playoffs",
}


@pytest.mark.parametrize("method_name", ["extract", "extract_all"])
@pytest.mark.asyncio
async def test_complete_observed_lineup_reaches_provider_constructor(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    extractor = TeamAndPlayersVsPlayersExtractor()
    captured: dict[str, object] = {}

    def _single(endpoint_cls: type, **kwargs: Any) -> pl.DataFrame:
        captured.update(endpoint_cls(get_request=False, **kwargs).parameters)
        return pl.DataFrame()

    def _multi(endpoint_cls: type, **kwargs: Any) -> list[pl.DataFrame]:
        captured.update(endpoint_cls(get_request=False, **kwargs).parameters)
        return [pl.DataFrame()]

    monkeypatch.setattr(extractor, "_from_nba_api", _single)
    monkeypatch.setattr(extractor, "_from_nba_api_multi", _multi)

    await getattr(extractor, method_name)(**_PARAMS)

    assert captured["TeamID"] == 1610612737
    assert captured["VsTeamID"] == 1610612738
    assert [captured[f"PlayerID{index}"] for index in range(1, 6)] == [
        101,
        102,
        103,
        104,
        105,
    ]
    assert [captured[f"VsPlayerID{index}"] for index in range(1, 6)] == [
        201,
        202,
        203,
        204,
        205,
    ]
    assert captured["Season"] == "2024-25"
    assert captured["SeasonType"] == "Playoffs"


@pytest.mark.parametrize(
    "updates, expected",
    [
        ({"vs_team_id": 1610612737}, "two distinct positive team IDs"),
        ({"player_id5": 101}, "two disjoint lineups"),
        ({"vs_player_id5": 101}, "two disjoint lineups"),
        ({"player_id1": 0}, "two disjoint lineups"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_lineup_fails_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
    updates: dict[str, object],
    expected: str,
) -> None:
    extractor = TeamAndPlayersVsPlayersExtractor()
    monkeypatch.setattr(
        extractor,
        "_from_nba_api",
        lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
    )
    params = {**_PARAMS, **updates}

    with pytest.raises(ValueError, match=expected):
        await extractor.extract(**params)


@pytest.mark.asyncio
async def test_missing_lineup_member_fails_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = TeamAndPlayersVsPlayersExtractor()
    monkeypatch.setattr(
        extractor,
        "_from_nba_api",
        lambda *_args, **_kwargs: pytest.fail("provider must not be called"),
    )
    params = {**_PARAMS}
    del params["vs_player_id5"]

    with pytest.raises(KeyError, match="vs_player_id5"):
        await extractor.extract(**params)
