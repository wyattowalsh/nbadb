from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from nbadb.extract.stats import misc


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def get_dict(self) -> dict[str, Any]:
        return self._payload


def _install_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _send(_self: object, **kwargs: Any) -> _FakeResponse:
        captured.update(kwargs)
        return _FakeResponse(payload)

    monkeypatch.setattr(misc.NBAStatsHTTP, "send_api_request", _send)
    return captured


def test_multiple_standard_result_sets_include_names_indexes_and_request_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_response(
        monkeypatch,
        {
            "resultSets": [
                {
                    "name": "Playlist",
                    "headers": ["GAME_ID", "EVENT_ID", "CONTEXT_MEASURE"],
                    "rowSet": [
                        ["0051900001", 1, "upstream-pts"],
                        ["0051900001", 2, "upstream-ast"],
                    ],
                },
                {
                    "name": "VideoUrls",
                    "headers": ["VIDEO_URL", "RESULT_SET_NAME", "RESULT_SET_INDEX"],
                    "data": [["https://cdn.nba.example/clip.mp4", "upstream", 99]],
                },
            ]
        },
    )
    extractor = misc.VideoDetailsExtractor()
    monkeypatch.setattr(extractor, "_inject_timeout", lambda _kwargs: None)
    monkeypatch.setattr(extractor, "_validate", lambda frame: frame)

    result = misc._extract_video_result_sets(
        extractor,
        misc.VideoDetails,
        player_id=2544,
        team_id=1610612739,
        season="2019-20",
        season_type="PlayIn",
        context_measure="OPP_FGM",
    )

    assert result.get_column("result_set_name").to_list() == [
        "Playlist",
        "Playlist",
        "VideoUrls",
    ]
    assert result.get_column("result_set_index").to_list() == [0, 0, 1]
    assert result.get_column("upstream_context_measure").to_list() == [
        "upstream-pts",
        "upstream-ast",
        None,
    ]
    assert result.get_column("upstream_result_set_name").to_list() == [None, None, "upstream"]
    assert result.get_column("upstream_result_set_index").to_list() == [None, None, 99]

    expected_provenance = {
        "context_measure": "OPP_FGM",
        "context_measure_provenance": "docs",
        "season_type_provenance": "runtime",
        "nba_api_contract_version": misc.NBA_API_VIDEO_CONTEXT_MEASURE_VERSION,
        "request_player_id": 2544,
        "request_team_id": 1610612739,
        "request_season": "2019-20",
        "request_season_type": "PlayIn",
    }
    for column, expected in expected_provenance.items():
        assert result.get_column(column).unique().to_list() == [expected]

    assert captured["endpoint"] == "videodetails"
    for parameter, expected in {
        "PlayerID": 2544,
        "TeamID": 1610612739,
        "Season": "2019-20",
        "SeasonType": "PlayIn",
        "ContextMeasure": "OPP_FGM",
    }.items():
        assert captured["parameters"][parameter] == expected


def test_nested_result_sets_use_stable_path_names() -> None:
    frames = misc._video_result_set_frames(
        {
            "resultSets": {
                "playlist": [
                    {"gameId": "0022400001", "eventId": 7},
                    {"gameId": "0022400001", "eventId": 8},
                ],
                "assets": {
                    "urls": [{"videoUrl": "https://cdn.nba.example/clip.mp4"}],
                    "metadata": {"provider": "NBA", "count": 1},
                },
            }
        }
    )

    assert [name for name, _frame in frames] == [
        "playlist",
        "assets.urls",
        "assets.metadata",
    ]
    frames_by_name = dict(frames)
    assert frames_by_name["playlist"].to_dicts() == [
        {"gameId": "0022400001", "eventId": 7},
        {"gameId": "0022400001", "eventId": 8},
    ]
    assert frames_by_name["assets.urls"].to_dicts() == [
        {"videoUrl": "https://cdn.nba.example/clip.mp4"}
    ]
    assert frames_by_name["assets.metadata"].to_dicts() == [{"provider": "NBA", "count": 1}]


@pytest.mark.parametrize(
    "payload",
    [{}, {"resultSet": []}, {"resultSets": []}, {"resultSets": {}}],
    ids=["empty-root", "empty-singular", "empty-list", "empty-mapping"],
)
def test_empty_responses_return_typed_provenance_frame(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    _install_response(monkeypatch, payload)
    extractor = misc.VideoDetailsExtractor()
    monkeypatch.setattr(extractor, "_inject_timeout", lambda _kwargs: None)
    monkeypatch.setattr(
        extractor,
        "_validate",
        lambda _frame: pytest.fail("empty responses must not enter schema validation"),
    )

    result = misc._extract_video_result_sets(
        extractor,
        misc.VideoDetails,
        player_id=1,
        team_id=10,
        season="2024-25",
        season_type="Regular Season",
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
