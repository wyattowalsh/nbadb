from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from nbadb.core.errors import ExtractionError, TransientError
from nbadb.extract.stats import misc


class _FakeResponse:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self._payload = payload
        self._status_code = status_code

    def get_dict(self) -> object:
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def _install_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    *,
    status_code: int = 200,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _send(_self: object, **kwargs: Any) -> _FakeResponse:
        captured.update(kwargs)
        return _FakeResponse(payload, status_code=status_code)

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


def test_heterogeneous_result_set_list_recurses_into_standard_and_dynamic_items() -> None:
    frames = misc._video_result_set_frames(
        {
            "resultSets": [
                {"name": "Standard", "headers": ["ID"], "rowSet": [[1]]},
                {"clips": [{"url": "https://cdn.nba.example/clip.mp4"}]},
                [["0022400001"], ["0022400002", 2]],
            ]
        }
    )

    assert [name for name, _frame in frames] == [
        "Standard",
        "result_set_1.clips",
        "result_set_2",
    ]
    assert frames[0][1].to_dicts() == [{"ID": 1}]
    assert frames[1][1].to_dicts() == [{"url": "https://cdn.nba.example/clip.mp4"}]
    assert frames[2][1].to_dicts() == [
        {"value_0": "0022400001", "value_1": None},
        {"value_0": "0022400002", "value_1": 2},
    ]


@pytest.mark.parametrize(
    "payload",
    [{"resultSet": []}, {"resultSets": []}, {"resultSets": {}}],
    ids=["empty-singular", "empty-list", "empty-mapping"],
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


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_retryable_non_2xx_response_is_rejected_as_transient_before_json_parsing(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    _install_response(
        monkeypatch,
        AssertionError("JSON parsing must not run"),
        status_code=status_code,
    )
    extractor = misc.VideoDetailsExtractor()
    monkeypatch.setattr(extractor, "_inject_timeout", lambda _kwargs: None)

    with pytest.raises(TransientError, match=f"upstream HTTP status {status_code}"):
        misc._extract_video_result_sets(
            extractor,
            misc.VideoDetails,
            player_id=1,
            team_id=10,
            season="2024-25",
            season_type="Regular Season",
            context_measure="PTS",
        )


def test_nonretryable_non_2xx_response_is_irrecoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_response(monkeypatch, {}, status_code=400)
    extractor = misc.VideoDetailsExtractor()
    monkeypatch.setattr(extractor, "_inject_timeout", lambda _kwargs: None)

    with pytest.raises(ExtractionError, match="upstream HTTP status 400"):
        misc._extract_video_result_sets(
            extractor,
            misc.VideoDetails,
            player_id=1,
            team_id=10,
            season="2024-25",
            season_type="Regular Season",
            context_measure="PTS",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"Message": "An error has occurred."},
        {"Message": "An error has occurred.", "resultSets": []},
        {"statusCode": 400, "message": "upstream failed"},
        {"error": {"code": "InvalidRequest"}},
    ],
    ids=["message", "message-with-results", "status", "error-field"],
)
def test_http_200_error_envelopes_are_rejected_before_result_parsing(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    _install_response(monkeypatch, payload)
    extractor = misc.VideoDetailsExtractor()
    monkeypatch.setattr(extractor, "_inject_timeout", lambda _kwargs: None)
    monkeypatch.setattr(
        misc,
        "_video_result_set_frames",
        lambda _payload: pytest.fail("error envelopes must not enter result-set parsing"),
    )

    with pytest.raises(ExtractionError, match="upstream JSON error envelope"):
        misc._extract_video_result_sets(
            extractor,
            misc.VideoDetails,
            player_id=1,
            team_id=10,
            season="2024-25",
            season_type="Regular Season",
            context_measure="PTS",
        )


@pytest.mark.parametrize("status_code", [429, 500, 503])
def test_http_200_retryable_error_envelopes_are_transient(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    _install_response(monkeypatch, {"statusCode": status_code, "message": "upstream failed"})
    extractor = misc.VideoDetailsExtractor()
    monkeypatch.setattr(extractor, "_inject_timeout", lambda _kwargs: None)

    with pytest.raises(TransientError, match="upstream JSON error envelope"):
        misc._extract_video_result_sets(
            extractor,
            misc.VideoDetails,
            player_id=1,
            team_id=10,
            season="2024-25",
            season_type="Regular Season",
            context_measure="PTS",
        )


@pytest.mark.parametrize(
    "payload",
    [{}, [], {"resultSets": "invalid"}, {"unexpected": "scalar"}],
    ids=["empty-object", "array-root", "scalar-container", "scalar-object"],
)
def test_malformed_video_roots_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    _install_response(monkeypatch, payload)
    extractor = misc.VideoDetailsExtractor()
    monkeypatch.setattr(extractor, "_inject_timeout", lambda _kwargs: None)

    with pytest.raises(ExtractionError, match="malformed video response root"):
        misc._extract_video_result_sets(
            extractor,
            misc.VideoDetails,
            player_id=1,
            team_id=10,
            season="2024-25",
            season_type="Regular Season",
            context_measure="PTS",
        )
