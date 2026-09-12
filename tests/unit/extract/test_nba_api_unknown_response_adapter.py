from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
import requests
from nba_api.stats.endpoints import (
    VideoDetails,
    VideoDetailsAsset,
    VideoEvents,
)
from nba_api.stats.endpoints.videoeventsasset import VideoEventsAsset
from nba_api.stats.library.http import NBAStatsResponse

from nbadb.core.errors import ResponseContractError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_endpoint_contract,
)
from nbadb.extract.bronze import (
    BronzeCaptureStore,
    BronzeLimits,
    ParserInputContext,
    canonical_parameters_sha256,
)
from nbadb.extract.nba_api_adapter import (
    NbaApiCaptureContract,
    NbaApiPayload,
    NbaApiResultPackets,
    NbaApiUnknownResponse,
    NbaDbStatsHTTP,
    fetch_stats_packets,
    fetch_stats_payload,
    replay_stats_packets,
    replay_stats_payload,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in unknown-response adapter tests")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)


_UNKNOWN_ENDPOINTS = (
    (
        VideoDetails,
        {"team_id": 1, "player_id": 2, "season": "2024-25"},
        "payload",
    ),
    (
        VideoDetailsAsset,
        {"team_id": 1, "player_id": 2, "season": "2024-25"},
        "payload",
    ),
    (
        VideoEvents,
        {"game_id": "0022400001", "game_event_id": 7},
        "packets",
    ),
    (
        VideoEventsAsset,
        {"game_id": "0022400001", "game_event_id": 7},
        "packets",
    ),
)


class _GenericZeroEndpoint:
    endpoint = "genericzero"
    expected_data = {}
    headers = None

    def __init__(
        self,
        item_id: int,
        *,
        proxy: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        get_request: bool = True,
    ) -> None:
        assert get_request is False
        self.parameters = {"ItemID": item_id}
        self.proxy = proxy
        self.timeout = timeout
        if headers is not None:
            self.headers = headers


def _capture_contract(
    root: Path,
    endpoint_cls: type,
    *,
    attempt_id: str = "unknown-response-attempt-1",
) -> NbaApiCaptureContract:
    store = BronzeCaptureStore(
        root / "private" / "bronze",
        public_roots=(root / "data" / "nbadb",),
        limits=BronzeLimits(
            max_response_bytes=1_000_000,
            max_generation_stored_bytes=2_000_000,
            minimum_free_bytes=1,
        ),
    )
    contract = pinned_endpoint_contract(endpoint_cls)
    return NbaApiCaptureContract(
        sink=store,
        context=ParserInputContext(attempt_id=attempt_id),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256=endpoint_contract_sha256(contract),
    )


def _install_raw_response(
    monkeypatch: pytest.MonkeyPatch,
    parser_input: str,
    *,
    status_code: int = 200,
) -> dict[str, Any]:
    request: dict[str, Any] = {}

    def _send(_self: object, **kwargs: Any) -> NBAStatsResponse:
        request.update(kwargs)
        return NBAStatsResponse(parser_input, status_code, "fixture://unknown-response")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _send)
    return request


def _fetch_unknown(
    endpoint_cls: type,
    mode: str,
    capture: NbaApiCaptureContract,
    kwargs: dict[str, Any],
) -> NbaApiPayload | NbaApiResultPackets:
    if mode == "payload":
        return fetch_stats_payload(endpoint_cls, capture=capture, **kwargs)
    return fetch_stats_packets(endpoint_cls, capture=capture, **kwargs)


def _replay_unknown(
    source: BronzeCaptureStore | SimpleNamespace,
    receipt_sha256: str,
    endpoint_cls: type,
    mode: str,
    kwargs: dict[str, Any],
) -> NbaApiPayload | NbaApiResultPackets:
    if mode == "payload":
        return replay_stats_payload(source, receipt_sha256, endpoint_cls, **kwargs)
    return replay_stats_packets(source, receipt_sha256, endpoint_cls, **kwargs)


def _unknown_observation(
    result: NbaApiPayload | NbaApiResultPackets,
) -> NbaApiUnknownResponse:
    observation = result.unknown_response
    assert observation is not None
    return observation


def _receipt_payload(capture: NbaApiCaptureContract, receipt_sha256: str) -> dict[str, Any]:
    store = cast("BronzeCaptureStore", capture.sink)
    path = next((store.root / "receipts" / "attempts").rglob(f"{receipt_sha256}.json"))
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("endpoint_cls", "kwargs", "mode"),
    _UNKNOWN_ENDPOINTS,
    ids=("video-details", "video-details-asset", "video-events", "video-events-asset"),
)
def test_exact_four_unknown_endpoints_capture_and_replay_generic_nested_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    endpoint_cls: type,
    kwargs: dict[str, Any],
    mode: str,
) -> None:
    parser_input = '{ "items": [], "data": {"missing": {}, "value": null} }'
    request = _install_raw_response(monkeypatch, parser_input)
    capture = _capture_contract(tmp_path, endpoint_cls)

    online = _fetch_unknown(endpoint_cls, mode, capture, kwargs)
    receipt = capture.receipt_snapshot().receipt_sha256s[0]
    observation = _unknown_observation(online)
    contract = pinned_endpoint_contract(endpoint_cls)
    recorded = capture.sink.load_recorded_attempt(receipt)

    assert observation.state == "generic_nested_json"
    assert observation.endpoint_id == endpoint_cls.__name__
    assert observation.endpoint_slug == endpoint_cls.endpoint
    assert observation.parameters_sha256 == canonical_parameters_sha256(request["parameters"])
    assert (
        observation.provider_authority_sha256
        == (expected_nba_api_provider_authority()["authority_sha256"])
    )
    assert observation.endpoint_contract_sha256 == endpoint_contract_sha256(contract)
    assert observation.response_mode_authority_sha256 == (
        contract.response_contract.authority_sha256
    )
    assert (
        observation.parser_input_sha256 == hashlib.sha256(parser_input.encode("utf-8")).hexdigest()
    )
    assert observation.canonical_payload_json == ('{"data":{"missing":{},"value":null},"items":[]}')
    assert (
        observation.canonical_payload_sha256
        == hashlib.sha256(observation.canonical_payload_json.encode("utf-8")).hexdigest()
    )
    assert observation.response_receipt_sha256 == receipt
    assert observation.occurrences == ()
    assert recorded.parser_input == parser_input.encode("utf-8")
    assert recorded.parameters_sha256 == observation.parameters_sha256
    assert recorded.endpoint_id == observation.endpoint_id
    assert recorded.endpoint_slug == observation.endpoint_slug
    assert recorded.outcome == "success_nonempty"
    if mode == "packets":
        assert tuple(online) == ()
    else:
        assert online == {
            "items": [],
            "data": {"missing": {}, "value": None},
        }

    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unknown-response replay must not perform transport")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _transport_forbidden)
    replayed = _replay_unknown(
        cast("BronzeCaptureStore", capture.sink),
        receipt,
        endpoint_cls,
        mode,
        kwargs,
    )

    assert _unknown_observation(replayed) == observation
    if mode == "payload":
        assert replayed == online
    else:
        assert tuple(replayed) == ()


def test_unknown_legacy_response_preserves_duplicate_occurrences_headers_and_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "resultSets": [
            {
                "name": "Observed",
                "headers": ["VALUE", "VALUE"],
                "rowSet": [[1, None], [True, "Ω"]],
            },
            {
                "name": "Observed",
                "headers": [],
                "rowSet": [[]],
            },
        ]
    }
    parser_input = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    _install_raw_response(monkeypatch, parser_input)
    capture = _capture_contract(tmp_path, VideoEvents)

    packets = fetch_stats_packets(
        VideoEvents,
        capture=capture,
        game_id="0022400001",
        game_event_id=7,
    )
    receipt = capture.receipt_snapshot().receipt_sha256s[0]
    observation = _unknown_observation(packets)
    recorded = capture.sink.load_recorded_attempt(receipt)

    assert tuple(packets) == ()
    assert observation.state == "legacy_present_nonempty"
    assert observation.legacy_envelope_name == "resultSets"
    assert [item.provider_index for item in observation.occurrences] == [0, 1]
    assert [item.name for item in observation.occurrences] == ["Observed", "Observed"]
    assert [item.headers for item in observation.occurrences] == [
        ("VALUE", "VALUE"),
        (),
    ]
    assert [item.receipt.row_count for item in observation.occurrences] == [2, 1]
    assert [cell.canonical_json for cell in observation.occurrences[0].rows[0]] == [
        "1",
        "null",
    ]
    assert [cell.value_kind for cell in observation.occurrences[0].rows[1]] == [
        "boolean",
        "string",
    ]
    assert observation.occurrences[1].rows == ((),)
    assert [item.name for item in recorded.result_sets] == ["Observed", "Observed"]
    assert [item.provider_index for item in recorded.result_sets] == [0, 1]
    assert recorded.outcome == "success_nonempty"

    replayed = replay_stats_packets(
        cast("BronzeCaptureStore", capture.sink),
        receipt,
        VideoEvents,
        game_id="0022400001",
        game_event_id=7,
    )

    assert _unknown_observation(replayed) == observation


@pytest.mark.parametrize(
    ("parser_input", "state", "occurrence_rows"),
    [
        ('{"resultSets":[]}', "legacy_present_empty", ()),
        (
            '{"resultSet":{"name":"Empty","headers":[],"rowSet":[]}}',
            "legacy_present_empty",
            (0,),
        ),
        ("{}", "missing_result_envelope", ()),
        ('{"statusText":"ok"}', "unknown_result_envelope", ()),
    ],
)
def test_unknown_response_distinguishes_empty_missing_and_unknown_envelopes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    parser_input: str,
    state: str,
    occurrence_rows: tuple[int, ...],
) -> None:
    _install_raw_response(monkeypatch, parser_input)
    capture = _capture_contract(tmp_path, VideoDetails)

    payload = fetch_stats_payload(
        VideoDetails,
        capture=capture,
        team_id=1,
        player_id=2,
        season="2024-25",
    )
    receipt = capture.receipt_snapshot().receipt_sha256s[0]
    observation = _unknown_observation(payload)
    recorded = capture.sink.load_recorded_attempt(receipt)

    assert observation.state == state
    assert tuple(item.receipt.row_count for item in observation.occurrences) == (occurrence_rows)
    assert recorded.outcome == (
        "success_empty"
        if state in {"legacy_present_empty", "missing_result_envelope"}
        else "success_nonempty"
    )


def test_unknown_generic_json_preserves_missing_versus_null(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observations: list[NbaApiUnknownResponse] = []
    for index, parser_input in enumerate(('{"data":{}}', '{"data":{"value":null}}')):
        _install_raw_response(monkeypatch, parser_input)
        capture = _capture_contract(
            tmp_path / str(index),
            VideoDetailsAsset,
            attempt_id=f"missing-null-{index}",
        )
        payload = fetch_stats_payload(
            VideoDetailsAsset,
            capture=capture,
            team_id=1,
            player_id=2,
            season="2024-25",
        )
        observations.append(_unknown_observation(payload))

    assert [item.state for item in observations] == [
        "generic_nested_json",
        "generic_nested_json",
    ]
    assert [item.canonical_payload_json for item in observations] == [
        '{"data":{}}',
        '{"data":{"value":null}}',
    ]
    assert observations[0].canonical_payload_sha256 != (observations[1].canonical_payload_sha256)
    assert observations[0].parser_input_sha256 != observations[1].parser_input_sha256


@pytest.mark.parametrize(
    "parser_input",
    [
        "[]",
        '{"resultSets":[],"resultSet":[]}',
        '{"resultSets":null}',
        '{"resultSets":[null]}',
        '{"resultSets":[{"headers":[],"rowSet":[]}]}',
        '{"resultSets":[{"name":"bad name","headers":[],"rowSet":[]}]}',
        '{"resultSets":[{"name":"Observed","headers":null,"rowSet":[]}]}',
        '{"resultSets":[{"name":"Observed","headers":[""],"rowSet":[]}]}',
        '{"resultSets":[{"name":"Observed","headers":["A"]}]}',
        '{"resultSets":[{"name":"Observed","headers":["A"],"rowSet":null}]}',
        '{"resultSets":[{"name":"Observed","headers":["A"],"rowSet":[[]]}]}',
        '{"resultSets":[{"name":"Observed","headers":[],"rowSet":[[1]]}]}',
    ],
)
def test_unknown_response_rejects_nonobject_ambiguous_and_malformed_legacy_shapes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    parser_input: str,
) -> None:
    _install_raw_response(monkeypatch, parser_input)
    capture = _capture_contract(tmp_path, VideoEventsAsset)

    with pytest.raises(ResponseContractError):
        fetch_stats_packets(
            VideoEventsAsset,
            capture=capture,
            game_id="0022400001",
            game_event_id=7,
        )

    snapshot = capture.receipt_snapshot()
    assert snapshot.successful_response_ordinals == ()
    recorded = capture.sink.load_recorded_attempt(snapshot.receipt_sha256s[0])
    assert recorded.parser_input == parser_input.encode("utf-8")
    assert recorded.outcome == "contract_mismatch"
    assert recorded.result_sets == ()


def test_unknown_response_records_malformed_json_body_without_parser_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parser_input = '{"data":'
    _install_raw_response(monkeypatch, parser_input)
    capture = _capture_contract(tmp_path, VideoDetails)

    with pytest.raises(ResponseContractError, match="malformed JSON"):
        fetch_stats_payload(
            VideoDetails,
            capture=capture,
            team_id=1,
            player_id=2,
            season="2024-25",
        )

    snapshot = capture.receipt_snapshot()
    assert snapshot.successful_response_ordinals == ()
    recorded = capture.sink.load_recorded_attempt(snapshot.receipt_sha256s[0])
    assert recorded.parser_input == parser_input.encode("utf-8")
    assert recorded.outcome == "malformed_json"


def test_unknown_response_records_transport_failure_without_an_invented_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _fail(_self: object, **_kwargs: Any) -> NBAStatsResponse:
        raise requests.Timeout("fixture timeout")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _fail)
    capture = _capture_contract(tmp_path, VideoEvents)

    with pytest.raises(requests.Timeout, match="fixture timeout"):
        fetch_stats_packets(
            VideoEvents,
            capture=capture,
            game_id="0022400001",
            game_event_id=7,
        )

    snapshot = capture.receipt_snapshot()
    assert snapshot.successful_response_ordinals == ()
    receipt = _receipt_payload(capture, snapshot.receipt_sha256s[0])
    assert receipt["outcome"] == "transport_failure_no_response"
    assert receipt["parser_input"] is None
    assert receipt["result_sets"] == []


def test_generic_zero_result_endpoint_remains_rejected_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = replace(
        pinned_endpoint_contract(VideoDetails),
        runtime_class_name=_GenericZeroEndpoint.__name__,
        module_name=_GenericZeroEndpoint.__module__,
        endpoint_slug=_GenericZeroEndpoint.endpoint,
    )
    monkeypatch.setattr(
        "nbadb.extract.nba_api_adapter.pinned_endpoint_contract",
        lambda _endpoint_cls: contract,
    )

    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("generic zero-result endpoint must fail before transport")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _transport_forbidden)

    with pytest.raises(ResponseContractError, match="response mode lacks pinned authority"):
        fetch_stats_payload(
            _GenericZeroEndpoint,
            endpoint_contract=contract,
            item_id=1,
        )


def test_unknown_replay_rejects_endpoint_parameter_and_body_substitution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parser_input = '{"data":{"value":null}}'
    _install_raw_response(monkeypatch, parser_input)
    capture = _capture_contract(tmp_path, VideoEvents)
    packets = fetch_stats_packets(
        VideoEvents,
        capture=capture,
        game_id="0022400001",
        game_event_id=7,
    )
    receipt = cast("str", _unknown_observation(packets).response_receipt_sha256)
    store = cast("BronzeCaptureStore", capture.sink)

    with pytest.raises(ResponseContractError, match="pinned provider contract"):
        replay_stats_packets(
            store,
            receipt,
            VideoEventsAsset,
            game_id="0022400001",
            game_event_id=7,
        )
    with pytest.raises(ResponseContractError, match="pinned provider contract"):
        replay_stats_packets(
            store,
            receipt,
            VideoEvents,
            game_id="0022400002",
            game_event_id=7,
        )

    recorded = store.load_recorded_attempt(receipt)
    substituted_source = SimpleNamespace(
        load_recorded_attempt=lambda _receipt: replace(
            recorded,
            parser_input=b'{"foreign":{}}',
        )
    )
    with pytest.raises(ResponseContractError, match="body authority"):
        replay_stats_packets(
            substituted_source,
            receipt,
            VideoEvents,
            game_id="0022400001",
            game_event_id=7,
        )


def test_unknown_observation_rejects_receipt_rebinding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_raw_response(monkeypatch, '{"data":{}}')
    capture = _capture_contract(tmp_path, VideoDetailsAsset)
    payload = fetch_stats_payload(
        VideoDetailsAsset,
        capture=capture,
        team_id=1,
        player_id=2,
        season="2024-25",
    )
    observation = _unknown_observation(payload)

    assert (
        observation.bind_response_receipt(cast("str", observation.response_receipt_sha256))
        == observation
    )
    with pytest.raises(ResponseContractError, match="cannot be rebound"):
        observation.bind_response_receipt("0" * 64)


def test_unknown_observation_rejects_structural_mutations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_raw_response(
        monkeypatch,
        '{"resultSet":{"name":"Observed","headers":["A"],"rowSet":[[1]]}}',
    )
    capture = _capture_contract(tmp_path, VideoEvents)
    packets = fetch_stats_packets(
        VideoEvents,
        capture=capture,
        game_id="0022400001",
        game_event_id=7,
    )
    observation = _unknown_observation(packets)
    occurrence = observation.occurrences[0]

    with pytest.raises(ResponseContractError, match="state is invalid"):
        replace(observation, state=cast("Any", "invented"))
    with pytest.raises(ResponseContractError, match="canonical payload drifted"):
        replace(observation, canonical_payload_json='{"foreign":{}}')
    with pytest.raises(ResponseContractError, match="receipt drifted"):
        replace(occurrence, headers=("B",))
    with pytest.raises(ResponseContractError, match="not immutable"):
        replace(observation, occurrences=cast("Any", list(observation.occurrences)))
