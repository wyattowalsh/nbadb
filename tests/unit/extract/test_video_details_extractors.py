from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from nbadb.extract.stats.misc import (
    VideoDetailsAssetExtractor,
    VideoDetailsExtractor,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def get_dict(self) -> dict[str, Any]:
        return self._payload


@pytest.mark.parametrize(
    ("extractor_cls", "expected_endpoint"),
    [
        (VideoDetailsExtractor, "videodetails"),
        (VideoDetailsAssetExtractor, "videodetailsasset"),
    ],
)
@pytest.mark.asyncio
async def test_preserves_all_named_result_sets_with_request_provenance(
    extractor_cls: type[VideoDetailsExtractor | VideoDetailsAssetExtractor],
    expected_endpoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    response = _FakeResponse(
        {
            "resultSets": [
                {
                    "name": "Playlist",
                    "headers": ["GAME_ID", "EVENT_ID", "CONTEXT_MEASURE"],
                    "rowSet": [
                        ["0051900001", 1, "upstream-a"],
                        ["0051900001", 2, "upstream-b"],
                    ],
                },
                {
                    "name": "VideoUrls",
                    "headers": ["GAME_ID", "VIDEO_URL", "RESULT_SET_NAME"],
                    "rowSet": [["0051900001", "https://cdn.nba.example/video.mp4", "upstream"]],
                },
            ]
        }
    )

    def _send(self, **kwargs: Any) -> _FakeResponse:
        captured.update(kwargs)
        return response

    monkeypatch.setattr(
        "nbadb.extract.stats.misc.NBAStatsHTTP.send_api_request",
        _send,
    )

    result = await extractor_cls().extract(
        player_id=2544,
        team_id=1610612739,
        season="2019-20",
        season_type="PlayIn",
        context_measure="OPP_FGM",
    )

    assert captured["endpoint"] == expected_endpoint
    assert captured["parameters"]["ContextMeasure"] == "OPP_FGM"
    assert captured["parameters"]["SeasonType"] == "PlayIn"
    assert result.height == 3
    assert result.get_column("result_set_name").to_list() == [
        "Playlist",
        "Playlist",
        "VideoUrls",
    ]
    assert result.get_column("result_set_index").to_list() == [0, 0, 1]
    assert result.get_column("context_measure").unique().to_list() == ["OPP_FGM"]
    assert result.get_column("context_measure_provenance").unique().to_list() == ["docs"]
    assert result.get_column("season_type_provenance").unique().to_list() == ["runtime"]
    assert result.get_column("nba_api_contract_version").unique().to_list() == ["1.11.4"]
    assert result.get_column("request_player_id").unique().to_list() == [2544]
    assert result.get_column("request_team_id").unique().to_list() == [1610612739]
    assert result.get_column("request_season").unique().to_list() == ["2019-20"]
    assert result.get_column("request_season_type").unique().to_list() == ["PlayIn"]
    assert "upstream_context_measure" in result.columns
    assert "upstream_result_set_name" in result.columns


@pytest.mark.asyncio
async def test_preserves_nested_dynamic_result_set_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nbadb.extract.stats.misc.NBAStatsHTTP.send_api_request",
        lambda self, **_kwargs: _FakeResponse(
            {
                "playlist": [{"gameId": "0022400001", "eventId": 1}],
                "assets": {
                    "urls": [
                        {
                            "gameId": "0022400001",
                            "url": "https://cdn.nba.example/video.mp4",
                        }
                    ]
                },
            }
        ),
    )

    result = await VideoDetailsExtractor().extract(
        player_id=1,
        team_id=10,
        season="2024-25",
        season_type="Regular Season",
        context_measure="PTS",
    )

    assert set(result.get_column("result_set_name")) == {"playlist", "assets.urls"}
    assert set(result.get_column("result_set_index")) == {0, 1}
    assert result.get_column("context_measure_provenance").unique().to_list() == ["docs,runtime"]


@pytest.mark.asyncio
async def test_preserves_named_dynamic_records_and_ragged_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nbadb.extract.stats.misc.NBAStatsHTTP.send_api_request",
        lambda self, **_kwargs: _FakeResponse(
            {
                "resultSets": {
                    "playlist": [{"name": "made basket", "eventId": 1}],
                    "matrix": [["0022400001"], ["0022400002", 2]],
                }
            }
        ),
    )

    result = await VideoDetailsExtractor().extract(
        player_id=1,
        team_id=10,
        season="2024-25",
        context_measure="PTS",
    )

    assert result.height == 3
    assert result.get_column("result_set_name").to_list() == ["playlist", "matrix", "matrix"]
    playlist = result.filter(pl.col("result_set_name") == "playlist")
    assert playlist.get_column("name").to_list() == ["made basket"]
    matrix = result.filter(pl.col("result_set_name") == "matrix")
    assert matrix.get_column("value_1").to_list() == [None, 2]


@pytest.mark.asyncio
async def test_empty_dynamic_response_keeps_provenance_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "nbadb.extract.stats.misc.NBAStatsHTTP.send_api_request",
        lambda self, **_kwargs: _FakeResponse({"resultSets": {}}),
    )

    result = await VideoDetailsAssetExtractor().extract(
        player_id=1,
        team_id=10,
        season="2024-25",
        context_measure="PTS",
    )

    assert result.is_empty()
    assert result.schema == {
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


@pytest.mark.asyncio
async def test_rejects_context_measure_outside_pinned_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send = monkeypatch.setattr(
        "nbadb.extract.stats.misc.NBAStatsHTTP.send_api_request",
        lambda self, **_kwargs: pytest.fail("network call must not run"),
    )

    with pytest.raises(ValueError, match="not a valid VideoContextMeasure"):
        await VideoDetailsExtractor().extract(
            player_id=1,
            team_id=10,
            season="2024-25",
            context_measure="UNKNOWN",
        )

    assert send is None
