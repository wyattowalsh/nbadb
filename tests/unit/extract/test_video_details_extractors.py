from __future__ import annotations

import json
import socket
from typing import TYPE_CHECKING, Any, cast

import polars as pl
import pytest

from nbadb.core.errors import ResponseContractError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.extract.bronze import BronzeCaptureStore, BronzeLimits, ParserInputContext
from nbadb.extract.nba_api_adapter import NbaApiCaptureContract, NbaDbStatsHTTP
from nbadb.extract.stats.misc import (
    VideoDetailsAssetExtractor,
    VideoDetailsExtractor,
    VideoEventsAssetExtractor,
    VideoEventsExtractor,
)

if TYPE_CHECKING:
    from pathlib import Path


class _FakeResponse:
    def __init__(self, parser_input: str) -> None:
        self._parser_input = parser_input
        self._status_code = 200

    def get_response(self) -> str:
        return self._parser_input

    def get_dict(self) -> object:
        return json.loads(self._parser_input)


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in captured video extractor tests")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)


def _capture_contract(root: Path, attempt_id: str) -> NbaApiCaptureContract:
    store = BronzeCaptureStore(
        root / "private" / "bronze",
        public_roots=(root / "data" / "nbadb",),
        limits=BronzeLimits(
            max_response_bytes=1_000_000,
            max_generation_stored_bytes=2_000_000,
            minimum_free_bytes=1,
        ),
    )
    return NbaApiCaptureContract(
        sink=store,
        context=ParserInputContext(attempt_id=attempt_id),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256="0" * 64,
    )


_CAPTURED_VIDEO_EXTRACTORS = (
    (
        VideoDetailsExtractor,
        {
            "player_id": 2,
            "team_id": 1,
            "season": "2024-25",
            "season_type": "Regular Season",
            "context_measure": "PTS",
        },
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
    ),
    (
        VideoEventsExtractor,
        {"game_id": "0022400001", "game_event_id": 71},
    ),
    (
        VideoEventsAssetExtractor,
        {"game_id": "0022400001", "game_event_id": 71},
    ),
)

_EXPLICIT_VIDEO_COMPETITIONS = ("00", "01", "10", "15", "20")


@pytest.mark.parametrize(
    "extractor_cls",
    (VideoDetailsExtractor, VideoDetailsAssetExtractor),
    ids=("details", "details-asset"),
)
@pytest.mark.parametrize("league_id", _EXPLICIT_VIDEO_COMPETITIONS)
@pytest.mark.asyncio
async def test_explicit_competition_reaches_exact_league_id_wire_parameter(
    monkeypatch: pytest.MonkeyPatch,
    extractor_cls: type[VideoDetailsExtractor | VideoDetailsAssetExtractor],
    league_id: str,
) -> None:
    request: dict[str, Any] = {}

    def _send(_self: object, **kwargs: Any) -> _FakeResponse:
        request.update(kwargs)
        return _FakeResponse('{"resultSets":[]}')

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _send)

    await extractor_cls().extract(
        player_id=2,
        team_id=1,
        season="2024-25",
        season_type="Regular Season",
        context_measure="PTS",
        league_id=league_id,
    )

    assert request["parameters"]["LeagueID"] == league_id


@pytest.mark.parametrize(
    "extractor_cls",
    (VideoDetailsExtractor, VideoDetailsAssetExtractor),
    ids=("details", "details-asset"),
)
@pytest.mark.parametrize(
    "scope_params",
    (
        {"league_id": ""},
        {"league_id_nullable": " "},
        {"league_id": "00", "league_id_nullable": "10"},
    ),
    ids=("empty-logical", "blank-constructor", "conflicting-aliases"),
)
@pytest.mark.asyncio
async def test_invalid_explicit_competition_fails_before_transport(
    monkeypatch: pytest.MonkeyPatch,
    extractor_cls: type[VideoDetailsExtractor | VideoDetailsAssetExtractor],
    scope_params: dict[str, str],
) -> None:
    monkeypatch.setattr(
        NbaDbStatsHTTP,
        "send_api_request",
        lambda _self, **_kwargs: pytest.fail("invalid competition must fail before transport"),
    )

    with pytest.raises(ResponseContractError, match="video competition scope"):
        await extractor_cls().extract(
            player_id=2,
            team_id=1,
            season="2024-25",
            season_type="Regular Season",
            context_measure="PTS",
            **scope_params,
        )


@pytest.mark.parametrize(
    ("extractor_cls", "params"),
    _CAPTURED_VIDEO_EXTRACTORS,
    ids=("details", "details-asset", "events", "events-asset"),
)
@pytest.mark.asyncio
async def test_exact_four_propagate_exact_response_receipt_to_typed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    extractor_cls: type[
        VideoDetailsExtractor
        | VideoDetailsAssetExtractor
        | VideoEventsExtractor
        | VideoEventsAssetExtractor
    ],
    params: dict[str, Any],
) -> None:
    parser_input = '{ "data": {"value": null}, "items": [] }'
    request: dict[str, Any] = {}

    def _send(_self: object, **kwargs: Any) -> _FakeResponse:
        request.update(kwargs)
        return _FakeResponse(parser_input)

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _send)
    capture = _capture_contract(tmp_path, f"captured-{extractor_cls.endpoint_name}")
    extractor = extractor_cls()
    extractor.set_capture_contract(capture)

    result = await extractor.extract(**params)
    receipt_snapshot = extractor.capture_receipt_snapshot()
    observations = extractor.unknown_response_snapshot()

    assert result.equals(pl.DataFrame())
    assert receipt_snapshot is not None
    assert receipt_snapshot.successful_response_ordinals == (0,)
    receipt = receipt_snapshot.receipt_sha256s[0]
    assert len(observations) == 1
    observation = observations[0]
    assert observation.response_receipt_sha256 == receipt
    assert observation.state == "generic_nested_json"
    assert observation.parser_input_sha256 == (
        cast("BronzeCaptureStore", capture.sink)
        .load_recorded_attempt(receipt)
        .captured.response_sha256
    )
    recorded = capture.sink.load_recorded_attempt(receipt)
    assert recorded.parser_input == parser_input.encode("utf-8")
    assert recorded.parameters_sha256 == observation.parameters_sha256
    assert recorded.endpoint_id == observation.endpoint_id
    assert recorded.endpoint_slug == observation.endpoint_slug == request["endpoint"]
    assert recorded.endpoint_contract_sha256 == observation.endpoint_contract_sha256
    assert recorded.result_sets == ()
    assert recorded.outcome == "success_nonempty"
    if "game_event_id" in params:
        assert request["parameters"]["GameEventID"] == params["game_event_id"]


@pytest.mark.asyncio
async def test_successful_empty_unknown_response_retains_receipt_without_fixed_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        NbaDbStatsHTTP,
        "send_api_request",
        lambda _self, **_kwargs: _FakeResponse('{"resultSets":[]}'),
    )
    capture = _capture_contract(tmp_path, "captured-present-empty")
    extractor = VideoDetailsExtractor()
    extractor.set_capture_contract(capture)

    result = await extractor.extract(
        player_id=2,
        team_id=1,
        season="2024-25",
        season_type="Regular Season",
        context_measure="PTS",
    )
    receipt_snapshot = extractor.capture_receipt_snapshot()
    observation = extractor.unknown_response_snapshot()[0]

    assert result.columns == []
    assert receipt_snapshot is not None
    receipt = receipt_snapshot.receipt_sha256s[0]
    assert observation.response_receipt_sha256 == receipt
    assert observation.state == "legacy_present_empty"
    assert capture.sink.load_recorded_attempt(receipt).outcome == "success_empty"
