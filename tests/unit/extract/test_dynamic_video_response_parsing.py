from __future__ import annotations

import json
import socket
from typing import Any

import polars as pl
import pytest
import requests

from nbadb.core.errors import ResponseContractError
from nbadb.extract.nba_api_adapter import NbaDbStatsHTTP
from nbadb.extract.stats.misc import (
    VideoDetailsAssetExtractor,
    VideoDetailsExtractor,
    VideoEventsAssetExtractor,
    VideoEventsExtractor,
)


class _FakeResponse:
    def __init__(self, parser_input: str, *, status_code: int = 200) -> None:
        self._parser_input = parser_input
        self._status_code = status_code

    def get_response(self) -> str:
        return self._parser_input

    def get_dict(self) -> object:
        return json.loads(self._parser_input)


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in video extractor tests")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)


def _install_response(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> dict[str, Any]:
    request: dict[str, Any] = {}
    parser_input = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )

    def _send(_self: object, **kwargs: Any) -> _FakeResponse:
        request.update(kwargs)
        return _FakeResponse(parser_input)

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _send)
    return request


_VIDEO_EXTRACTORS = (
    (
        VideoDetailsExtractor,
        {
            "player_id": 2,
            "team_id": 1,
            "season": "2024-25",
            "season_type": "Regular Season",
            "context_measure": "PTS",
        },
        "VideoDetails",
        "videodetails",
    ),
    (
        VideoDetailsAssetExtractor,
        {
            "player_id": 2,
            "team_id": 1,
            "season": "2024-25",
            "season_type": "Regular Season",
            "context_measure": "PTS",
        },
        "VideoDetailsAsset",
        "videodetailsasset",
    ),
    (
        VideoEventsExtractor,
        {"game_id": "0022400001", "game_event_id": 37},
        "VideoEvents",
        "videoevents",
    ),
    (
        VideoEventsAssetExtractor,
        {"game_id": "0022400001", "game_event_id": 37},
        "VideoEventsAsset",
        "videoeventsasset",
    ),
)


@pytest.mark.parametrize(
    ("extractor_cls", "params", "endpoint_id", "endpoint_slug"),
    _VIDEO_EXTRACTORS,
    ids=("details", "details-asset", "events", "events-asset"),
)
@pytest.mark.asyncio
async def test_exact_four_retain_generic_json_without_invented_relational_columns(
    monkeypatch: pytest.MonkeyPatch,
    extractor_cls: type[
        VideoDetailsExtractor
        | VideoDetailsAssetExtractor
        | VideoEventsExtractor
        | VideoEventsAssetExtractor
    ],
    params: dict[str, Any],
    endpoint_id: str,
    endpoint_slug: str,
) -> None:
    request = _install_response(
        monkeypatch,
        {
            "playlist": [{"gameId": "0022400001", "eventId": 37}],
            "asset": {"url": None, "metadata": {}},
        },
    )
    extractor = extractor_cls()

    result = await extractor.extract(**params)
    observations = extractor.unknown_response_snapshot()

    assert result.equals(pl.DataFrame())
    assert result.columns == []
    assert len(observations) == 1
    observation = observations[0]
    assert observation.endpoint_id == endpoint_id
    assert observation.endpoint_slug == endpoint_slug
    assert observation.state == "generic_nested_json"
    assert observation.response_receipt_sha256 is None
    assert observation.canonical_payload_json == (
        '{"asset":{"metadata":{},"url":null},"playlist":[{"eventId":37,"gameId":"0022400001"}]}'
    )
    assert observation.occurrences == ()
    assert extractor.lossless_fallback_snapshot() == ()
    assert request["endpoint"] == endpoint_slug
    if "game_event_id" in params:
        assert request["parameters"]["GameEventID"] == params["game_event_id"]
    else:
        assert request["parameters"]["PlayerID"] == params["player_id"]
        assert request["parameters"]["TeamID"] == params["team_id"]
        assert request["parameters"]["Season"] == params["season"]
        assert request["parameters"]["SeasonType"] == params["season_type"]
        assert request["parameters"]["ContextMeasure"] == params["context_measure"]


@pytest.mark.asyncio
async def test_details_legacy_occurrence_remains_typed_and_out_of_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_response(
        monkeypatch,
        {
            "resultSet": {
                "name": "Observed",
                "headers": ["VALUE", "VALUE"],
                "rowSet": [[1, None], [True, "clip"]],
            }
        },
    )
    extractor = VideoDetailsExtractor()

    result = await extractor.extract(
        player_id=2,
        team_id=1,
        season="2024-25",
        season_type="Regular Season",
        context_measure="PTS",
    )
    observation = extractor.unknown_response_snapshot()[0]

    assert result.columns == []
    assert observation.state == "legacy_present_nonempty"
    assert observation.legacy_envelope_name == "resultSet"
    assert len(observation.occurrences) == 1
    occurrence = observation.occurrences[0]
    assert occurrence.name == "Observed"
    assert occurrence.headers == ("VALUE", "VALUE")
    assert occurrence.receipt.row_count == 2
    assert [cell.canonical_json for cell in occurrence.rows[0]] == ["1", "null"]


@pytest.mark.asyncio
async def test_details_asset_present_empty_is_not_fixed_result_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_response(monkeypatch, {"resultSets": []})
    extractor = VideoDetailsAssetExtractor()

    result = await extractor.extract(
        player_id=2,
        team_id=1,
        season="2024-25",
        season_type="Regular Season",
        context_measure="PTS",
    )
    observation = extractor.unknown_response_snapshot()[0]

    assert result.equals(pl.DataFrame())
    assert observation.state == "legacy_present_empty"
    assert observation.occurrences == ()
    assert observation.result_set_receipts == ()


@pytest.mark.parametrize(
    "extractor_cls",
    (VideoEventsExtractor, VideoEventsAssetExtractor),
    ids=("events", "events-asset"),
)
@pytest.mark.asyncio
async def test_video_events_require_caller_game_event_id_before_transport(
    monkeypatch: pytest.MonkeyPatch,
    extractor_cls: type[VideoEventsExtractor | VideoEventsAssetExtractor],
) -> None:
    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("missing game_event_id must fail before transport")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _transport_forbidden)

    with pytest.raises(KeyError, match="game_event_id"):
        await extractor_cls().extract(game_id="0022400001")


@pytest.mark.asyncio
async def test_contract_failure_does_not_create_unknown_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        NbaDbStatsHTTP,
        "send_api_request",
        lambda _self, **_kwargs: _FakeResponse('{"resultSets":null}'),
    )
    extractor = VideoDetailsExtractor()

    with pytest.raises(ResponseContractError, match="legacy envelope"):
        await extractor.extract(
            player_id=2,
            team_id=1,
            season="2024-25",
            season_type="Regular Season",
            context_measure="PTS",
        )

    assert extractor.unknown_response_snapshot() == ()


@pytest.mark.asyncio
async def test_transport_failure_does_not_create_unknown_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(_self: object, **_kwargs: Any) -> _FakeResponse:
        raise requests.Timeout("fixture timeout")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _fail)
    extractor = VideoEventsExtractor()

    with pytest.raises(requests.Timeout, match="fixture timeout"):
        await extractor.extract(game_id="0022400001", game_event_id=37)

    assert extractor.unknown_response_snapshot() == ()


@pytest.mark.asyncio
async def test_invalid_context_measure_fails_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("invalid context measure must fail before transport")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _transport_forbidden)

    with pytest.raises(ValueError, match="not a valid VideoContextMeasure"):
        await VideoDetailsExtractor().extract(
            player_id=2,
            team_id=1,
            season="2024-25",
            season_type="Regular Season",
            context_measure="UNKNOWN",
        )
