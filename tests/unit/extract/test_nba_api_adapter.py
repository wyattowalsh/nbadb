from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import polars as pl
import pytest
from nba_api.library.http import NBAResponse
from nba_api.live.nba.endpoints import PlayByPlay, ScoreBoard
from nba_api.stats.endpoints import PlayByPlayV3
from nba_api.stats.library.http import NBAStatsResponse

from nbadb.core.errors import (
    ExtractionError,
    ParserInputCaptureIntegrityError,
    ResponseContractError,
)
from nbadb.core.extraction_failures import classify_exception
from nbadb.core.nba_api_contract import build_endpoint_contract
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    owned_contract_sha256,
    pinned_endpoint_contract,
    pinned_live_endpoint_contract,
    pinned_static_dataset_contract,
)
from nbadb.extract.bronze import (
    BronzeCaptureStore,
    BronzeLimits,
    ParserInputContext,
    parent_occurrence_states_digest,
    result_sets_digest,
)
from nbadb.extract.nba_api_adapter import (
    LOSSLESS_FALLBACK_SCHEMA,
    NbaApiCaptureContract,
    NbaApiReceiptLedger,
    NbaApiResultPackets,
    NbaDbLiveHTTP,
    NbaDbStatsHTTP,
    UpstreamApplicationError,
    UpstreamHttpError,
    UpstreamTransientHttpError,
    fetch_live_payloads,
    fetch_static_packet,
    fetch_stats_packets,
    fetch_stats_payload,
    replay_live_payloads,
    replay_static_packet,
    replay_stats_packets,
    replay_stats_payload,
    rows_to_polars,
    validate_lossless_fallback_frame,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access is forbidden in adapter tests")

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)


class _LegacyEndpoint:
    endpoint = "fixtureendpoint"
    expected_data = {"Stats": ["ID", "VALUE"]}
    headers = None

    def __init__(
        self,
        item_id: int,
        *,
        proxy: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | tuple[float, float] = 30,
        get_request: bool = True,
    ) -> None:
        assert get_request is False
        self.parameters = {"ItemID": item_id}
        self.proxy = proxy
        self.timeout = timeout
        if headers is not None:
            self.headers = headers


class _LegacyMultiEndpoint:
    endpoint = "fixturemultiendpoint"
    expected_data = {
        "First": ["ID", "VALUE"],
        "Second": ["LABEL"],
    }
    headers = None

    def __init__(
        self,
        item_id: int,
        *,
        proxy: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | tuple[float, float] = 30,
        get_request: bool = True,
    ) -> None:
        assert get_request is False
        self.parameters = {"ItemID": item_id}
        self.proxy = proxy
        self.timeout = timeout
        if headers is not None:
            self.headers = headers


_LEGACY_CONTRACT = build_endpoint_contract(_LegacyEndpoint)
_LEGACY_CONTRACT_SHA256 = endpoint_contract_sha256(_LEGACY_CONTRACT)
_LEGACY_MULTI_CONTRACT = build_endpoint_contract(_LegacyMultiEndpoint)


@pytest.fixture(autouse=True)
def _pin_fixture_endpoint_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def _resolve(runtime_cls: type):
        if runtime_cls is _LegacyEndpoint:
            return _LEGACY_CONTRACT
        if runtime_cls is _LegacyMultiEndpoint:
            return _LEGACY_MULTI_CONTRACT
        return pinned_endpoint_contract(runtime_cls)

    monkeypatch.setattr(
        "nbadb.extract.nba_api_adapter.pinned_endpoint_contract",
        _resolve,
    )


def _stats_response(payload: object, status: int = 200) -> NBAStatsResponse:
    return NBAStatsResponse(json.dumps(payload), status, "fixture://stats")


def _live_response(payload: object, status: int = 200) -> NBAResponse:
    return NBAResponse(json.dumps(payload), status, "fixture://live")


def _play_by_play_v3_payload() -> dict[str, Any]:
    return {
        "game": {
            "gameId": "0022400001",
            "videoAvailable": 1,
            "actions": [
                {
                    "actionNumber": 7,
                    "clock": "PT11M00S",
                    "period": 1,
                    "teamId": 1,
                    "teamTricode": "AAA",
                    "personId": 2,
                    "playerName": "Player",
                    "playerNameI": "P. Player",
                    "xLegacy": 3,
                    "yLegacy": 4,
                    "shotDistance": 5,
                    "shotResult": "Made",
                    "isFieldGoal": 1,
                    "scoreHome": "2",
                    "scoreAway": "0",
                    "pointsTotal": 2,
                    "location": "h",
                    "description": "fixture",
                    "actionType": "2pt",
                    "subType": "Jump Shot",
                    "videoAvailable": 1,
                    "shotValue": 2,
                    "actionId": 70,
                }
            ],
        }
    }


def _packet_signature(packet: object) -> tuple[object, ...]:
    owned = cast("Any", packet)
    return (
        owned.name,
        owned.provider_index,
        owned.canonical_index,
        owned.headers,
        owned.frame.to_dicts(),
        owned.response_receipt_sha256,
        owned.provider_authority_sha256,
        owned.endpoint_contract_sha256,
    )


def _tamper_attempt_receipt(
    store: BronzeCaptureStore,
    receipt_sha256: str,
    **changes: object,
) -> str:
    receipt_path = next((store.root / "receipts" / "attempts").rglob(f"{receipt_sha256}.json"))
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload.update(changes)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    tampered_digest = hashlib.sha256(encoded).hexdigest()
    tampered_path = (
        store.root / "receipts" / "attempts" / tampered_digest[:2] / f"{tampered_digest}.json"
    )
    tampered_path.parent.mkdir(parents=True, exist_ok=True)
    tampered_path.write_bytes(encoded)
    return tampered_digest


def _install_stats_response(
    monkeypatch: pytest.MonkeyPatch,
    response: NBAStatsResponse,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _send(_self: object, **kwargs: Any) -> NBAStatsResponse:
        captured.update(kwargs)
        return response

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _send)
    return captured


def _capture_contract(tmp_path: Path) -> NbaApiCaptureContract:
    store = BronzeCaptureStore(
        tmp_path / "private" / "bronze",
        public_roots=(tmp_path / "data" / "nbadb",),
        limits=BronzeLimits(
            max_response_bytes=1_000_000,
            max_generation_stored_bytes=2_000_000,
            minimum_free_bytes=1,
        ),
    )
    return NbaApiCaptureContract(
        sink=store,
        context=ParserInputContext(attempt_id="adapter-attempt-1"),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256=_LEGACY_CONTRACT_SHA256,
    )


def _stats_capture_contract(tmp_path: Path, endpoint_cls: type) -> NbaApiCaptureContract:
    capture = _capture_contract(tmp_path)
    if endpoint_cls is _LegacyEndpoint:
        contract = _LEGACY_CONTRACT
    elif endpoint_cls is _LegacyMultiEndpoint:
        contract = _LEGACY_MULTI_CONTRACT
    else:
        contract = pinned_endpoint_contract(endpoint_cls)
    return replace(
        capture,
        endpoint_contract_sha256=endpoint_contract_sha256(contract),
    )


def _live_capture_contract(
    tmp_path: Path,
    endpoint_cls: type = PlayByPlay,
) -> NbaApiCaptureContract:
    contract = pinned_live_endpoint_contract(endpoint_cls)
    capture = _capture_contract(tmp_path)
    return replace(
        capture,
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256=owned_contract_sha256(contract),
    )


def _static_capture_contract(tmp_path: Path, dataset_id: str) -> NbaApiCaptureContract:
    capture = _capture_contract(tmp_path)
    contract = pinned_static_dataset_contract(dataset_id)
    return replace(
        capture,
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256=owned_contract_sha256(contract),
    )


def test_legacy_packet_preserves_order_values_and_request_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _stats_response(
        {
            "resultSets": [
                {
                    "name": "Stats",
                    "headers": ["ID", "VALUE"],
                    "rowSet": [[1, "one"], [2, None]],
                }
            ]
        }
    )
    captured = _install_stats_response(monkeypatch, response)

    packets = fetch_stats_packets(
        _LegacyEndpoint,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=7,
        timeout=(3.05, 9.0),
    )

    assert len(packets) == 1
    packet = packets[0]
    assert packet.name == "Stats"
    assert packet.provider_index == packet.canonical_index == 0
    assert packet.headers == ("ID", "VALUE")
    assert packet.frame.to_dicts() == [
        {"ID": 1, "VALUE": "one"},
        {"ID": 2, "VALUE": None},
    ]
    assert captured["endpoint"] == "fixtureendpoint"
    assert captured["parameters"] == {"ItemID": 7}
    assert captured["timeout"] == (3.05, 9.0)
    assert tuple(captured["headers"]) == tuple(NbaDbStatsHTTP.headers)


def test_stats_capture_and_parser_reuse_one_immutable_response_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_payload = {
        "resultSets": [
            {
                "name": "Stats",
                "headers": ["ID", "VALUE"],
                "rowSet": [[1, "first"]],
            }
        ]
    }
    first_text = json.dumps(first_payload)

    class MutatingResponse(NBAStatsResponse):
        reads = 0

        def get_response(self) -> str:
            self.reads += 1
            return first_text if self.reads == 1 else '{"mutated":true}'

    response = MutatingResponse(first_text, 200, "fixture://mutating")
    _install_stats_response(monkeypatch, response)
    capture = _stats_capture_contract(tmp_path, _LegacyEndpoint)

    packets = fetch_stats_packets(
        _LegacyEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=7,
    )

    assert response.reads == 1
    assert packets[0].frame.to_dicts() == [{"ID": 1, "VALUE": "first"}]
    entry = capture.receipt_snapshot().entries[0]
    assert capture.sink.replay_parser_input(entry.receipt_sha256) == first_text.encode()


def test_custom_stats_parser_reuses_immutable_body_without_reentering_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_text = json.dumps(_play_by_play_v3_payload())

    class MutatingCustomResponse(NBAStatsResponse):
        reads = 0

        def get_response(self) -> str:
            self.reads += 1
            return first_text if self.reads == 1 else '{"game":{"actions":[]}}'

        def get_data_sets(self, _endpoint: str) -> dict[str, object]:
            raise AssertionError("the mutable provider response parser must not be re-entered")

    response = MutatingCustomResponse(first_text, 200, "fixture://mutating-custom")
    _install_stats_response(monkeypatch, response)
    capture = _stats_capture_contract(tmp_path, PlayByPlayV3)

    packets = fetch_stats_packets(
        PlayByPlayV3,
        capture=capture,
        game_id="0022400001",
    )

    assert response.reads == 1
    assert [packet.name for packet in packets] == ["AvailableVideo", "PlayByPlay"]
    assert packets[1].frame["actionNumber"].to_list() == [7]
    entry = capture.receipt_snapshot().entries[0]
    assert capture.sink.replay_parser_input(entry.receipt_sha256) == first_text.encode()


def test_stats_error_body_is_captured_before_any_provider_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parser_input = '{"Message":"An error has occurred."}'
    assert NbaDbStatsHTTP().clean_contents(parser_input) == parser_input
    _install_stats_response(monkeypatch, NBAStatsResponse(parser_input, 200, "fixture://stats"))
    capture = _capture_contract(tmp_path)

    with pytest.raises(UpstreamApplicationError):
        fetch_stats_packets(
            _LegacyEndpoint,
            capture=capture,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=7,
        )

    snapshot = capture.receipt_snapshot()
    assert len(snapshot.receipt_sha256s) == 1
    assert capture.sink.replay_parser_input(snapshot.receipt_sha256s[0]).decode() == parser_input


def test_runtime_expected_data_mutation_cannot_change_owned_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response(
            {
                "resultSets": [
                    {
                        "name": "Stats",
                        "headers": ["ID", "VALUE"],
                        "rowSet": [[1, "one"]],
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(_LegacyEndpoint, "expected_data", {"Drifted": ["BAD"]})

    packets = fetch_stats_packets(
        _LegacyEndpoint,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=1,
    )

    assert [packet.name for packet in packets] == ["Stats"]


def test_capture_contract_digest_mismatch_fails_before_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = _install_stats_response(monkeypatch, _stats_response({}))
    capture = replace(_capture_contract(tmp_path), endpoint_contract_sha256="0" * 64)

    with pytest.raises(ResponseContractError, match="capture authority"):
        fetch_stats_packets(
            _LegacyEndpoint,
            capture=capture,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=1,
        )

    assert sent == {}


def test_stats_capture_provider_authority_mismatch_fails_before_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = _install_stats_response(monkeypatch, _stats_response({}))
    capture = replace(_capture_contract(tmp_path), provider_authority_sha256="a" * 64)

    with pytest.raises(ResponseContractError, match="capture authority"):
        fetch_stats_packets(
            _LegacyEndpoint,
            capture=capture,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=1,
        )

    assert sent == {}


def test_supplied_stats_contract_cannot_replace_packaged_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = _install_stats_response(monkeypatch, _stats_response({}))
    drifted_result_set = replace(
        _LEGACY_CONTRACT.result_sets[0],
        expected_columns=("ID", "MUTATED"),
    )
    supplied = replace(_LEGACY_CONTRACT, result_sets=(drifted_result_set,))

    with pytest.raises(ResponseContractError, match="supplied endpoint contract"):
        fetch_stats_packets(
            _LegacyEndpoint,
            endpoint_contract=supplied,
            item_id=1,
        )

    assert sent == {}


def test_ambiguous_legacy_result_envelopes_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stats_response(monkeypatch, _stats_response({"resultSets": [], "resultSet": {}}))

    with pytest.raises(ResponseContractError):
        fetch_stats_packets(
            _LegacyEndpoint,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=1,
        )


@pytest.mark.parametrize(
    ("payload", "expected_reasons", "expected_wide_packets"),
    [
        (
            {
                "resultSets": [
                    {"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]},
                    {"name": "Extra", "headers": ["EXTRA"], "rowSet": [[9]]},
                ]
            },
            {"additive_result_set"},
            1,
        ),
        (
            {"resultSets": [{"name": "Stats", "headers": ["ID"], "rowSet": [[1, 2]]}]},
            {"ragged_row", "removed_header"},
            0,
        ),
        (
            {"resultSets": [{"name": "Stats", "headers": ["VALUE", "ID"], "rowSet": [["one", 1]]}]},
            {"reordered_header"},
            0,
        ),
        (
            {"resultSets": [{"name": "Stats", "headers": ["ID", "ID"], "rowSet": [[1, 2]]}]},
            {"additive_header", "duplicate_header", "removed_header"},
            0,
        ),
        (
            {
                "resultSets": [
                    {"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]},
                    {"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[2, "two"]]},
                ]
            },
            {"additive_result_set", "duplicate_result_set_name"},
            0,
        ),
        (
            {
                "resultSets": [
                    {
                        "name": "Stats",
                        "headers": ["ID", "VALUE"],
                        "rowSet": [[1, 1], [2, "two"], [3, None]],
                    }
                ]
            },
            {"heterogeneous_column"},
            0,
        ),
    ],
)
def test_successful_stats_shape_drift_uses_lossless_fallback(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
    expected_reasons: set[str],
    expected_wide_packets: int,
) -> None:
    _install_stats_response(monkeypatch, _stats_response(payload))

    packets = fetch_stats_packets(
        _LegacyEndpoint,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=1,
    )

    assert isinstance(packets, tuple)
    assert isinstance(packets, NbaApiResultPackets)
    assert len(packets) == expected_wide_packets
    fallback = packets.lossless_fallback
    assert fallback is not None
    assert set(fallback.reason_codes) == expected_reasons
    assert fallback.frame.schema == LOSSLESS_FALLBACK_SCHEMA
    validate_lossless_fallback_frame(fallback.frame)


def test_lossless_fallback_retains_occurrences_ordinals_values_and_empty_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "resultSets": [
            {
                "name": "Stats",
                "headers": ["ID", "ID"],
                "rowSet": [[1, {"nested": [True, None]}], [1, {"nested": [True, None]}]],
            },
            {"name": "Stats", "headers": ["EMPTY", "EMPTY"], "rowSet": []},
        ]
    }
    _install_stats_response(monkeypatch, _stats_response(payload))

    packets = fetch_stats_packets(
        _LegacyEndpoint,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=1,
    )

    assert not packets
    fallback = packets.lossless_fallback
    assert fallback is not None
    records = fallback.frame.to_dicts()
    result_sets = [row for row in records if row["record_kind"] == "result_set"]
    assert [row["result_set_occurrence"] for row in result_sets] == [0, 1]
    headers = [row for row in records if row["record_kind"] == "header"]
    assert [(row["provider_index"], row["header_ordinal"]) for row in headers] == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]
    row_records = [row for row in records if row["record_kind"] == "row"]
    assert [row["row_ordinal"] for row in row_records] == [0, 1]
    cells = [row for row in records if row["record_kind"] == "cell"]
    assert [(row["row_ordinal"], row["header_ordinal"]) for row in cells] == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]
    assert cells[1]["value_kind"] == "object"
    assert cells[1]["canonical_json"] == '{"nested":[true,null]}'


def test_removed_result_set_is_an_explicit_missing_fallback_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response(
            {"resultSets": [{"name": "First", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]}]}
        ),
    )

    packets = fetch_stats_packets(
        _LegacyMultiEndpoint,
        endpoint_contract=_LEGACY_MULTI_CONTRACT,
        item_id=1,
    )

    assert not packets
    fallback = packets.lossless_fallback
    assert fallback is not None
    assert fallback.reason_codes == ("missing_result_set",)
    missing = fallback.frame.filter(pl.col("record_kind") == "missing_expected").to_dicts()
    assert [(row["result_set_name"], row["canonical_index"]) for row in missing] == [("Second", 1)]
    missing_receipt = fallback.result_set_receipts[-1]
    assert missing_receipt.name == "Second"
    assert missing_receipt.provider_index is None
    assert missing_receipt.canonical_index is None
    assert missing_receipt.missing_count == 1


def test_all_removed_result_sets_retain_every_expected_typed_empty_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stats_response(monkeypatch, _stats_response({"resultSets": []}))

    packets = fetch_stats_packets(
        _LegacyMultiEndpoint,
        endpoint_contract=_LEGACY_MULTI_CONTRACT,
        item_id=1,
    )

    assert not packets
    fallback = packets.lossless_fallback
    assert fallback is not None
    assert fallback.provider_result_set_count == 0
    assert fallback.expected_result_set_count == 2
    assert fallback.reason_codes == ("missing_result_set",)
    assert fallback.frame.get_column("record_kind").to_list() == [
        "missing_expected",
        "missing_expected",
    ]
    assert fallback.frame.get_column("result_set_name").to_list() == ["First", "Second"]
    assert fallback.frame.get_column("canonical_index").to_list() == [0, 1]
    assert [receipt.missing_count for receipt in fallback.result_set_receipts] == [1, 1]


def test_http_status_survives_owned_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stats_response(monkeypatch, _stats_response({}, status=503))

    with pytest.raises(UpstreamTransientHttpError) as exc_info:
        fetch_stats_packets(
            _LegacyEndpoint,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=1,
        )

    assert exc_info.value.status_code == 503
    assert classify_exception(exc_info.value) == "transport_transient"


def test_nonretryable_http_status_is_application(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stats_response(monkeypatch, _stats_response({}, status=400))

    with pytest.raises(UpstreamHttpError) as exc_info:
        fetch_stats_packets(
            _LegacyEndpoint,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=1,
        )

    assert classify_exception(exc_info.value) == "application"


def test_play_by_play_custom_parser_is_reordered_and_keeps_shot_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stats_response(monkeypatch, _stats_response(_play_by_play_v3_payload()))

    packets = fetch_stats_packets(PlayByPlayV3, game_id="0022400001")

    assert [packet.name for packet in packets] == ["AvailableVideo", "PlayByPlay"]
    assert [packet.provider_index for packet in packets] == [1, 0]
    assert packets[1].headers[-2:] == ("shotValue", "actionId")
    assert packets[1].frame["shotValue"].to_list() == [2]


def test_rows_to_polars_fails_closed_on_mixed_json_value_types() -> None:
    with pytest.raises(ResponseContractError, match="heterogeneous JSON value types"):
        rows_to_polars(("VALUE",), ((1,), ("oops",), (None,)))


def test_rows_to_polars_uses_null_columns_for_untyped_empty_packets() -> None:
    frame = rows_to_polars(("VALUE",), ())

    assert frame.schema == {"VALUE": pl.Null}


@pytest.mark.parametrize("rows", [[], [[1, "same"], [1, "same"]]])
def test_strict_known_empty_and_duplicate_rows_preserve_packet_behavior(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[list[object]],
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response(
            {"resultSets": [{"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": rows}]}
        ),
    )

    packets = fetch_stats_packets(
        _LegacyEndpoint,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=1,
    )

    assert len(packets) == 1
    assert packets.lossless_fallback is None
    assert packets[0].frame.height == len(rows)
    assert packets[0].frame.columns == ["ID", "VALUE"]
    if rows:
        assert packets[0].frame.rows() == [(1, "same"), (1, "same")]


def test_live_root_validation_distinguishes_present_empty_from_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _send(_self: object, **_kwargs: Any) -> NBAResponse:
        return _live_response({"meta": {"code": 200}, "game": {"actions": []}})

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)
    result = fetch_live_payloads(
        PlayByPlay,
        {"actions": "game_actions"},
        game_id="0022400001",
    )
    assert result == {"actions": []}

    def _missing(_self: object, **_kwargs: Any) -> NBAResponse:
        return _live_response({"meta": {"code": 200}, "game": {}})

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _missing)
    with pytest.raises(ResponseContractError, match="absent from response"):
        fetch_live_payloads(PlayByPlay, {"actions": "game_actions"}, game_id="0022400001")


def test_live_packet_validates_every_list_item(monkeypatch: pytest.MonkeyPatch) -> None:
    def _send(_self: object, **_kwargs: Any) -> NBAResponse:
        return _live_response(
            {
                "meta": {"code": 200},
                "game": {
                    "actions": [
                        {
                            "actionNumber": 1,
                            "clock": "PT11M00S",
                            "timeActual": "2025-01-01T00:00:00Z",
                            "period": 1,
                            "periodType": "REGULAR",
                            "actionType": "period",
                            "qualifiers": [],
                            "personId": 0,
                            "x": None,
                            "y": None,
                            "possession": 0,
                            "scoreHome": "0",
                            "scoreAway": "0",
                            "orderNumber": 1,
                            "xLegacy": None,
                            "yLegacy": None,
                            "isFieldGoal": 0,
                            "side": None,
                            "personIdsFilter": [],
                        },
                        2,
                    ]
                },
            }
        )

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)

    with pytest.raises(ResponseContractError, match="contain only objects"):
        fetch_live_payloads(PlayByPlay, {"actions": "game_actions"}, game_id="0022400001")


@pytest.mark.parametrize(
    "selection,game_id,error",
    [
        ({"actions": "not_a_pinned_result_set"}, "0022400001", "pinned nbadb authority"),
        (
            {"first": "game_actions", "second": "game_actions"},
            "0022400001",
            "selected more than once",
        ),
        ({"actions": "game_actions"}, "001", "pinned pattern"),
    ],
)
def test_live_contract_rejects_invalid_selection_or_parameters_before_send(
    monkeypatch: pytest.MonkeyPatch,
    selection: dict[str, str],
    game_id: str,
    error: str,
) -> None:
    def _unexpected_send(_self: object, **_kwargs: Any) -> NBAResponse:
        raise AssertionError("invalid live contracts must fail before transport")

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _unexpected_send)

    with pytest.raises(ResponseContractError, match=error):
        fetch_live_payloads(PlayByPlay, selection, game_id=game_id)


def test_live_capture_rejects_wrong_endpoint_authority_before_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _unexpected_send(_self: object, **_kwargs: Any) -> NBAResponse:
        raise AssertionError("invalid capture authority must fail before transport")

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _unexpected_send)
    capture = replace(_live_capture_contract(tmp_path), endpoint_contract_sha256="f" * 64)

    with pytest.raises(ResponseContractError, match="capture authority"):
        fetch_live_payloads(
            PlayByPlay,
            {"actions": "game_actions"},
            capture=capture,
            game_id="0022400001",
        )


def test_live_request_and_receipt_use_exact_generated_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent: dict[str, Any] = {}

    def _send(_self: object, **kwargs: Any) -> NBAResponse:
        sent.update(kwargs)
        return _live_response({"meta": {"code": 200}, "game": {"actions": []}})

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)
    capture = _live_capture_contract(tmp_path)
    contract = pinned_live_endpoint_contract(PlayByPlay)
    result_set = next(item for item in contract.result_sets if item.name == "game_actions")

    result = fetch_live_payloads(
        PlayByPlay,
        {"actions": "game_actions"},
        capture=capture,
        game_id="0022400001",
    )

    assert sent["endpoint"] == contract.endpoint_url_template.format(game_id="0022400001")
    assert sent["parameters"] == {}
    assert tuple(sent["headers"].items()) == tuple(NbaDbLiveHTTP.headers.items())
    assert result.response_receipt_sha256 is not None
    receipt_path = next(
        (capture.sink.root / "receipts" / "attempts").rglob(
            f"{result.response_receipt_sha256}.json"
        )
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["endpoint_id"] == contract.endpoint_id
    assert receipt["endpoint_slug"] == contract.endpoint_slug
    assert receipt["endpoint_contract_sha256"] == owned_contract_sha256(contract)
    result_receipts = receipt["result_sets"]
    assert [item["name"] for item in result_receipts] == [
        item.name for item in contract.result_sets
    ]
    assert [item["canonical_index"] for item in result_receipts] == list(
        range(len(contract.result_sets))
    )
    assert {item["provider_index"] for item in result_receipts} == {None}
    selected_receipt = next(item for item in result_receipts if item["name"] == result_set.name)
    expected_headers_sha256 = hashlib.sha256(
        json.dumps(
            [field.name for field in result_set.fields],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert selected_receipt["headers_sha256"] == expected_headers_sha256
    assert selected_receipt["json_path"] == result_set.json_path
    assert selected_receipt["container_kind"] == result_set.container_kind
    assert selected_receipt["container_count"] == 1
    assert selected_receipt["row_count"] == 0
    assert selected_receipt["missing_count"] == 0
    assert selected_receipt["null_count"] == 0
    assert selected_receipt["parent_observation_count"] == 1
    assert selected_receipt["parent_occurrence_states_sha256"] == (
        parent_occurrence_states_digest(("present",))
    )


def test_live_additive_sibling_is_captured_before_drift_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _send(_self: object, **_kwargs: Any) -> NBAResponse:
        return _live_response(
            {
                "meta": {"code": 200},
                "game": {"actions": [], "unexpectedAdditiveField": "fixture"},
            }
        )

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)
    capture = _live_capture_contract(tmp_path)

    with pytest.raises(ResponseContractError, match="additive unclassified"):
        fetch_live_payloads(
            PlayByPlay,
            {"actions": "game_actions"},
            capture=capture,
            game_id="0022400001",
        )

    snapshot = capture.receipt_snapshot()
    assert snapshot.successful_response_ordinals == ()
    assert len(snapshot.receipt_sha256s) == 1
    receipt_path = next(
        (capture.sink.root / "receipts" / "attempts").rglob(f"{snapshot.receipt_sha256s[0]}.json")
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["outcome"] == "contract_mismatch"
    replay = json.loads(capture.sink.replay_parser_input(snapshot.receipt_sha256s[0]))
    assert replay["game"]["unexpectedAdditiveField"] == "fixture"


def test_scoreboard_traverses_game_leaders_and_receipts_every_nested_dataset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "meta": {},
        "scoreboard": {
            "games": [
                {
                    "homeTeam": {"periods": []},
                    "awayTeam": {"periods": []},
                    "gameLeaders": {
                        "homeLeaders": {},
                        "awayLeaders": {},
                    },
                    "pbOdds": {},
                },
                {
                    "homeTeam": {"periods": []},
                    "awayTeam": {"periods": []},
                    "pbOdds": {},
                },
                {
                    "homeTeam": {"periods": []},
                    "awayTeam": {"periods": []},
                    "gameLeaders": None,
                    "pbOdds": {},
                },
            ]
        },
    }

    def _send(_self: object, **_kwargs: Any) -> NBAResponse:
        return _live_response(payload)

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)
    capture = _live_capture_contract(tmp_path, ScoreBoard)
    contract = pinned_live_endpoint_contract(ScoreBoard)

    result = fetch_live_payloads(
        ScoreBoard,
        {"games": "scoreboard_games"},
        capture=capture,
    )

    assert result == {"games": payload["scoreboard"]["games"]}
    receipt_path = next(
        (capture.sink.root / "receipts" / "attempts").rglob(
            f"{result.response_receipt_sha256}.json"
        )
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    result_receipts = receipt["result_sets"]
    assert [item["name"] for item in result_receipts] == [
        item.name for item in contract.result_sets
    ]
    assert len(result_receipts) == 11
    by_name = {item["name"]: item for item in result_receipts}
    game_leaders = by_name["scoreboard_games_gameleaders"]
    assert game_leaders["container_count"] == 1
    assert game_leaders["row_count"] == 1
    assert game_leaders["missing_count"] == 1
    assert game_leaders["null_count"] == 1
    assert game_leaders["parent_observation_count"] == 3
    assert game_leaders["parent_occurrence_states_sha256"] == (
        parent_occurrence_states_digest(("present", "missing", "null"))
    )
    assert by_name["scoreboard_games_hometeam_periods"]["container_count"] == 3
    assert by_name["scoreboard_games_hometeam_periods"]["row_count"] == 0
    assert by_name["scoreboard_games_awayteam_periods"]["container_count"] == 3
    assert by_name["scoreboard_games_awayteam_periods"]["row_count"] == 0


def test_live_duplicate_json_keys_are_captured_then_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parser_input = '{"meta":{"code":200,"code":201},"game":{"actions":[]}}'

    def _send(_self: object, **_kwargs: Any) -> NBAResponse:
        return NBAResponse(parser_input, 200, "fixture://live")

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)
    capture = _live_capture_contract(tmp_path)

    with pytest.raises(ResponseContractError, match="duplicate object keys"):
        fetch_live_payloads(
            PlayByPlay,
            {"actions": "game_actions"},
            capture=capture,
            game_id="0022400001",
        )

    snapshot = capture.receipt_snapshot()
    assert len(snapshot.receipt_sha256s) == 1
    assert capture.sink.replay_parser_input(snapshot.receipt_sha256s[0]).decode() == parser_input


def test_live_receipt_is_independent_of_selected_packet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {
        "meta": {"code": 200},
        "game": {"gameId": "0022400001", "actions": []},
    }

    def _send(_self: object, **_kwargs: Any) -> NBAResponse:
        return _live_response(payload)

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)
    game_capture = _live_capture_contract(tmp_path / "game")
    actions_capture = _live_capture_contract(tmp_path / "actions")

    game = fetch_live_payloads(
        PlayByPlay,
        {"game": "game"},
        capture=game_capture,
        game_id="0022400001",
    )
    actions = fetch_live_payloads(
        PlayByPlay,
        {"actions": "game_actions"},
        capture=actions_capture,
        game_id="0022400001",
    )

    assert game == {"game": payload["game"]}
    assert actions == {"actions": []}
    assert game.response_receipt_sha256 == actions.response_receipt_sha256


def test_provider_sessions_are_thread_local_and_ignore_ambient_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid")
    NbaDbStatsHTTP.evict_session()

    first = NbaDbStatsHTTP.get_session()
    second = NbaDbStatsHTTP.get_session()

    assert first is second
    assert first.trust_env is False
    NbaDbStatsHTTP.evict_session()


def test_successful_packet_retains_private_response_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response(
            {
                "resultSets": [
                    {
                        "name": "Stats",
                        "headers": ["ID", "VALUE"],
                        "rowSet": [[1, "one"]],
                    }
                ]
            }
        ),
    )
    capture = _capture_contract(tmp_path)

    packets = fetch_stats_packets(
        _LegacyEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=1,
    )

    assert len(packets) == 1
    assert packets[0].response_receipt_sha256 is not None
    assert (
        packets[0].provider_authority_sha256
        == (expected_nba_api_provider_authority()["authority_sha256"])
    )
    assert packets[0].endpoint_contract_sha256 == _LEGACY_CONTRACT_SHA256
    receipt_path = next(
        (capture.sink.root / "receipts" / "attempts").rglob(
            f"{packets[0].response_receipt_sha256}.json"
        )
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    result_set = receipt["result_sets"][0]
    assert result_set["parent_observation_count"] == 1
    assert result_set["parent_occurrence_states_sha256"] == (
        parent_occurrence_states_digest(("present",))
    )
    replay = capture.sink.replay_parser_input(packets[0].response_receipt_sha256)
    assert json.loads(replay) == {
        "resultSets": [{"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]}]
    }


def test_drifted_response_is_captured_as_success_and_replays_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response({"resultSets": [{"name": "Stats", "headers": ["ID"], "rowSet": [[1, 2]]}]}),
    )
    capture = _capture_contract(tmp_path)

    online = fetch_stats_packets(
        _LegacyEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=1,
    )

    receipts = list((capture.sink.root / "receipts" / "attempts").rglob("*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["outcome"] == "success_nonempty"
    assert receipt["failure_class"] is None
    assert receipt["parser_input"]["response_sha256"]
    assert receipt["result_sets"][0]["canonical_index"] is None
    assert capture.receipt_snapshot().successful_response_ordinals == (0,)
    online_fallback = online.lossless_fallback
    assert online_fallback is not None
    assert online_fallback.response_receipt_sha256 == receipts[0].stem

    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("fallback replay must not perform transport")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _transport_forbidden)
    replayed = replay_stats_packets(
        capture.sink,
        receipts[0].stem,
        _LegacyEndpoint,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=1,
    )
    replayed_fallback = replayed.lossless_fallback
    assert replayed_fallback is not None
    assert replayed_fallback.reason_codes == online_fallback.reason_codes
    assert replayed_fallback.frame.equals(online_fallback.frame)


def test_non_2xx_response_body_is_captured_before_status_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_stats_response(monkeypatch, _stats_response({"error": "blocked"}, status=503))
    capture = _capture_contract(tmp_path)

    with pytest.raises(UpstreamTransientHttpError):
        fetch_stats_packets(
            _LegacyEndpoint,
            capture=capture,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=1,
        )

    receipt_path = next((capture.sink.root / "receipts" / "attempts").rglob("*.json"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status_code"] == 503
    assert receipt["effective_status_code"] == 503
    assert receipt["outcome"] == "http_transient_error"
    assert capture.sink.replay_parser_input(receipt_path.stem) == b'{"error": "blocked"}'


@pytest.mark.parametrize("embedded_status", [429, 503])
def test_embedded_transient_status_retains_transport_and_effective_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    embedded_status: int,
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response({"statusCode": embedded_status}, status=200),
    )
    capture = _capture_contract(tmp_path)

    with pytest.raises(UpstreamTransientHttpError) as exc_info:
        fetch_stats_packets(
            _LegacyEndpoint,
            capture=capture,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=1,
        )

    assert exc_info.value.status_code == embedded_status
    receipt_path = next((capture.sink.root / "receipts" / "attempts").rglob("*.json"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status_code"] == 200
    assert receipt["effective_status_code"] == embedded_status
    assert receipt["outcome"] == "http_transient_error"
    assert capture.receipt_snapshot().successful_response_ordinals == ()


def test_malformed_json_has_owned_outcome_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_stats_response(monkeypatch, NBAStatsResponse("{", 200, "fixture://stats"))
    capture = _capture_contract(tmp_path)

    with pytest.raises(ResponseContractError, match="malformed JSON"):
        fetch_stats_packets(
            _LegacyEndpoint,
            capture=capture,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=1,
        )

    receipt_path = next((capture.sink.root / "receipts" / "attempts").rglob("*.json"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["outcome"] == "malformed_json"
    assert receipt["failure_class"] == "response_contract"


def test_receipt_ledger_binds_no_response_then_success_in_request_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response = _stats_response(
        {"resultSets": [{"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]}]}
    )
    calls = 0

    def _send(_self: object, **_kwargs: Any) -> NBAStatsResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("do not persist")
        return response

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _send)
    capture = _capture_contract(tmp_path)

    with pytest.raises(TimeoutError):
        fetch_stats_packets(
            _LegacyEndpoint,
            capture=capture,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=1,
        )
    fetch_stats_packets(
        _LegacyEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=1,
    )

    snapshot = capture.receipt_snapshot()
    assert [(entry.context.request_ordinal, entry.successful) for entry in snapshot.entries] == [
        (0, False),
        (1, True),
    ]
    call_digest = capture.sink.record_logical_call(
        context=capture.context,
        logical_endpoint_id="fixture_endpoint",
        logical_parameters={"item_id": 1},
        provider_authority_sha256=capture.provider_authority_sha256,
        response_receipt_sha256s=snapshot.receipt_sha256s,
        successful_response_ordinals=snapshot.successful_response_ordinals,
        result_route_ids=("stg_fixture",),
    )
    assert len(call_digest) == 64


def test_receipt_ledger_rejects_outstanding_context_substitution_and_post_seal() -> None:
    ledger = NbaApiReceiptLedger()
    base = ParserInputContext(attempt_id="attempt-1", lane_id="lane-1")
    allocated = ledger.allocate(base)

    with pytest.raises(ParserInputCaptureIntegrityError, match="outstanding"):
        ledger.snapshot()
    with pytest.raises(ParserInputCaptureIntegrityError, match="context differs"):
        ledger.record(
            replace(allocated, lane_id="lane-2"),
            "a" * 64,
            successful=False,
        )

    ledger.record(allocated, "a" * 64, successful=False)
    snapshot = ledger.snapshot()
    assert snapshot.receipt_sha256s == ("a" * 64,)
    assert ledger.snapshot() is snapshot
    with pytest.raises(ParserInputCaptureIntegrityError, match="sealed"):
        ledger.allocate(base)


def test_receipt_ledger_requires_contiguous_retries_and_requests() -> None:
    ledger = NbaApiReceiptLedger()
    base = ParserInputContext(attempt_id="attempt-1")
    first = ledger.allocate(base)
    ledger.record(first, "a" * 64, successful=False)

    second = ledger.allocate(base)
    assert (second.retry_ordinal, second.request_ordinal) == (0, 1)
    ledger.record(second, "b" * 64, successful=False)
    with pytest.raises(ParserInputCaptureIntegrityError, match="contiguous"):
        ledger.allocate(replace(base, retry_ordinal=2))

    retry = ledger.allocate(replace(base, retry_ordinal=1))
    assert (retry.retry_ordinal, retry.request_ordinal) == (1, 0)
    ledger.record(retry, "c" * 64, successful=True)
    assert [
        (entry.context.retry_ordinal, entry.context.request_ordinal)
        for entry in ledger.snapshot().entries
    ] == [(0, 0), (0, 1), (1, 0)]


def test_live_capture_retains_complete_envelope_not_only_selected_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _send(_self: object, **_kwargs: Any) -> NBAResponse:
        return _live_response(
            {
                "meta": {"code": 200},
                "game": {"gameId": "0022400001", "actions": []},
            }
        )

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)
    capture = _live_capture_contract(tmp_path)

    result = fetch_live_payloads(
        PlayByPlay,
        {"actions": "game_actions"},
        capture=capture,
        game_id="0022400001",
    )

    assert result == {"actions": []}
    assert result.response_receipt_sha256 is not None
    replay = json.loads(capture.sink.replay_parser_input(result.response_receipt_sha256))
    assert replay["game"]["gameId"] == "0022400001"


def test_static_teams_capture_precedes_projection_and_retains_championships(
    tmp_path: Path,
) -> None:
    capture = _static_capture_contract(tmp_path, "static_teams")
    contract = pinned_static_dataset_contract("static_teams")

    packet = fetch_static_packet("static_teams", capture=capture)

    assert packet.name == "teams_shape_1"
    assert packet.headers == tuple(field.name for field in contract.raw_fields)
    assert packet.frame.shape == (30, 8)
    assert packet.frame.schema["championship_year"] == pl.List(pl.Int64)
    championship_lists = packet.frame["championship_year"].to_list()
    assert sum(bool(years) for years in championship_lists) == 20
    assert sum(len(years) for years in championship_lists) == 77
    assert packet.response_receipt_sha256 is not None
    receipt_path = next(
        (capture.sink.root / "receipts" / "attempts").rglob(
            f"{packet.response_receipt_sha256}.json"
        )
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["transport_kind"] == "static_provider_snapshot"
    assert receipt["status_code"] is None
    assert receipt["endpoint_id"] == "static_teams"
    assert receipt["endpoint_slug"] == "teams"
    assert receipt["result_sets"][0]["name"] == "teams_shape_1"
    assert receipt["result_sets"][0]["parent_observation_count"] == 1
    assert receipt["result_sets"][0]["parent_occurrence_states_sha256"] == (
        parent_occurrence_states_digest(("present",))
    )
    replay = json.loads(capture.sink.replay_parser_input(packet.response_receipt_sha256))
    assert len(replay) == 30
    assert replay[0][-1] == championship_lists[0]


def test_static_players_exact_raw_shape_and_receipt(tmp_path: Path) -> None:
    capture = _static_capture_contract(tmp_path, "static_players")

    packet = fetch_static_packet("static_players", capture=capture)

    assert packet.headers == ("id", "last_name", "first_name", "full_name", "is_active")
    assert packet.frame.shape == (5103, 5)
    assert packet.response_receipt_sha256 is not None
    assert capture.receipt_snapshot().successful_response_ordinals == (0,)


@pytest.mark.parametrize(
    ("dataset_id", "expected_name", "expected_shape", "expected_headers"),
    [
        (
            "static_wnba_players",
            "wnba_players_shape_1",
            (1147, 5),
            ("id", "last_name", "first_name", "full_name", "is_active"),
        ),
        (
            "static_wnba_teams",
            "wnba_teams_shape_1",
            (13, 8),
            (
                "id",
                "abbreviation",
                "nickname",
                "year_founded",
                "city",
                "full_name",
                "state",
                "championship_year",
            ),
        ),
    ],
)
def test_static_wnba_snapshots_preserve_exact_embedded_rows_without_transport(
    dataset_id: str,
    expected_name: str,
    expected_shape: tuple[int, int],
    expected_headers: tuple[str, ...],
) -> None:
    packet = fetch_static_packet(dataset_id)

    assert packet.name == expected_name
    assert packet.headers == expected_headers
    assert packet.frame.shape == expected_shape
    if dataset_id == "static_wnba_teams":
        championship_lists = packet.frame["championship_year"].to_list()
        assert sum(bool(years) for years in championship_lists) == 9
        assert sum(len(years) for years in championship_lists) == 22


def test_static_capture_authority_fails_before_source_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    capture = replace(
        _static_capture_contract(tmp_path, "static_teams"),
        endpoint_contract_sha256="f" * 64,
    )

    def _unexpected_import(_name: str) -> object:
        raise AssertionError("invalid static authority must fail before provider import")

    monkeypatch.setattr("nbadb.extract.nba_api_adapter.importlib.import_module", _unexpected_import)

    with pytest.raises(ResponseContractError, match="capture authority"):
        fetch_static_packet("static_teams", capture=capture)


def test_static_mutation_is_captured_before_contract_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nba_api.stats.library import data as static_data

    capture = _static_capture_contract(tmp_path, "static_teams")
    mutated = json.loads(json.dumps(static_data.teams))
    mutated[0][1] = "MUTATED"
    monkeypatch.setattr(
        "nbadb.extract.nba_api_adapter.importlib.import_module",
        lambda _name: SimpleNamespace(teams=mutated),
    )

    with pytest.raises(ResponseContractError, match="content differs"):
        fetch_static_packet("static_teams", capture=capture)

    snapshot = capture.receipt_snapshot()
    assert snapshot.successful_response_ordinals == ()
    replay = json.loads(capture.sink.replay_parser_input(snapshot.receipt_sha256s[0]))
    assert replay[0][1] == "MUTATED"


def test_static_missing_source_records_failure_without_http_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    capture = _static_capture_contract(tmp_path, "static_teams")
    monkeypatch.setattr(
        "nbadb.extract.nba_api_adapter.importlib.import_module",
        lambda _name: SimpleNamespace(),
    )

    with pytest.raises(ResponseContractError, match="source is unavailable"):
        fetch_static_packet("static_teams", capture=capture)

    receipt_digest = capture.receipt_snapshot().receipt_sha256s[0]
    receipt_path = next(
        (capture.sink.root / "receipts" / "attempts").rglob(f"{receipt_digest}.json")
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["transport_kind"] == "static_provider_snapshot"
    assert receipt["status_code"] is None
    assert receipt["effective_status_code"] is None
    assert receipt["parser_input"] is None
    assert receipt["outcome"] == "contract_mismatch"


@pytest.mark.parametrize("dataset_id", ["unknown"])
def test_static_unknown_dataset_fails_before_capture(
    dataset_id: str,
) -> None:
    with pytest.raises(ResponseContractError, match="static dataset"):
        fetch_static_packet(dataset_id)


@pytest.mark.parametrize(
    ("provider_names", "provider_indexes"),
    [
        (("First", "Second"), (0, 1)),
        (("Second", "First"), (1, 0)),
    ],
)
def test_legacy_multi_packet_replay_preserves_ordered_and_reordered_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_names: tuple[str, str],
    provider_indexes: tuple[int, int],
) -> None:
    result_sets = {
        "First": {
            "name": "First",
            "headers": ["ID", "VALUE"],
            "rowSet": [[1, "one"]],
        },
        "Second": {"name": "Second", "headers": ["LABEL"], "rowSet": [["two"]]},
    }
    _install_stats_response(
        monkeypatch,
        _stats_response({"resultSets": [result_sets[name] for name in provider_names]}),
    )
    capture = _stats_capture_contract(tmp_path, _LegacyMultiEndpoint)
    online = fetch_stats_packets(
        _LegacyMultiEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_MULTI_CONTRACT,
        item_id=7,
    )
    receipt = capture.receipt_snapshot().receipt_sha256s[0]

    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replay must not perform stats transport")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _transport_forbidden)
    replayed = replay_stats_packets(
        capture.sink,
        receipt,
        _LegacyMultiEndpoint,
        endpoint_contract=_LEGACY_MULTI_CONTRACT,
        item_id=7,
    )

    assert [_packet_signature(packet) for packet in replayed] == [
        _packet_signature(packet) for packet in online
    ]
    assert [packet.name for packet in replayed] == ["First", "Second"]
    assert [packet.provider_index for packet in replayed] == list(provider_indexes)
    assert [item.name for item in capture.sink.load_recorded_attempt(receipt).result_sets] == [
        "First",
        "Second",
    ]


def test_stats_payload_replay_preserves_payload_and_receipt_digests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response(
            {"resultSets": [{"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]}]}
        ),
    )
    capture = _capture_contract(tmp_path)
    online = fetch_stats_payload(
        _LegacyEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=7,
    )
    receipt = capture.receipt_snapshot().receipt_sha256s[0]

    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replay must not perform stats transport")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _transport_forbidden)
    replayed = replay_stats_payload(
        capture.sink,
        receipt,
        _LegacyEndpoint,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=7,
    )

    assert replayed == online
    assert replayed.response_receipt_sha256 == online.response_receipt_sha256 == receipt
    assert replayed.provider_authority_sha256 == online.provider_authority_sha256
    assert replayed.endpoint_contract_sha256 == online.endpoint_contract_sha256


def test_custom_v3_packet_replay_matches_online_parser_and_digests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_stats_response(monkeypatch, _stats_response(_play_by_play_v3_payload()))
    capture = _stats_capture_contract(tmp_path, PlayByPlayV3)
    online = fetch_stats_packets(
        PlayByPlayV3,
        capture=capture,
        game_id="0022400001",
    )
    receipt = capture.receipt_snapshot().receipt_sha256s[0]

    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replay must not perform stats transport")

    monkeypatch.setattr(NbaDbStatsHTTP, "send_api_request", _transport_forbidden)
    replayed = replay_stats_packets(
        capture.sink,
        receipt,
        PlayByPlayV3,
        game_id="0022400001",
    )

    assert [_packet_signature(packet) for packet in replayed] == [
        _packet_signature(packet) for packet in online
    ]
    assert [packet.name for packet in replayed] == ["AvailableVideo", "PlayByPlay"]
    assert [packet.provider_index for packet in replayed] == [1, 0]


def test_live_empty_replay_matches_payload_receipts_and_digests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _send(_self: object, **_kwargs: Any) -> NBAResponse:
        return _live_response({"meta": {"code": 200}, "game": {"actions": []}})

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)
    capture = _live_capture_contract(tmp_path)
    online = fetch_live_payloads(
        PlayByPlay,
        {"actions": "game_actions"},
        capture=capture,
        game_id="0022400001",
    )
    receipt = capture.receipt_snapshot().receipt_sha256s[0]

    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replay must not perform live transport")

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _transport_forbidden)
    replayed = replay_live_payloads(
        capture.sink,
        receipt,
        PlayByPlay,
        {"actions": "game_actions"},
        game_id="0022400001",
    )

    assert replayed == online == {"actions": []}
    assert replayed.response_receipt_sha256 == online.response_receipt_sha256 == receipt
    assert replayed.provider_authority_sha256 == online.provider_authority_sha256
    assert replayed.endpoint_contract_sha256 == online.endpoint_contract_sha256
    assert replayed.result_set_receipts == online.result_set_receipts


def test_static_replay_uses_recorded_snapshot_without_provider_import(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    capture = _static_capture_contract(tmp_path, "static_teams")
    online = fetch_static_packet("static_teams", capture=capture)
    receipt = capture.receipt_snapshot().receipt_sha256s[0]

    def _provider_import_forbidden(_name: str) -> object:
        raise AssertionError("static replay must not import provider rows")

    monkeypatch.setattr(
        "nbadb.extract.nba_api_adapter.importlib.import_module",
        _provider_import_forbidden,
    )
    replayed = replay_static_packet(capture.sink, receipt, "static_teams")

    assert _packet_signature(replayed) == _packet_signature(online)


def test_replay_rejects_parameter_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response(
            {"resultSets": [{"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]}]}
        ),
    )
    capture = _capture_contract(tmp_path)
    online = fetch_stats_packets(
        _LegacyEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=7,
    )

    with pytest.raises(ResponseContractError, match="pinned provider contract"):
        replay_stats_packets(
            capture.sink,
            cast("str", online[0].response_receipt_sha256),
            _LegacyEndpoint,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=8,
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"provider_authority_sha256": "0" * 64},
        {"endpoint_contract_sha256": "f" * 64},
    ],
)
def test_replay_rejects_mismatched_provider_or_contract_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed: dict[str, str],
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response(
            {"resultSets": [{"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]}]}
        ),
    )
    capture = _capture_contract(tmp_path)
    online = fetch_stats_packets(
        _LegacyEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=7,
    )
    receipt = cast("str", online[0].response_receipt_sha256)
    store = cast("BronzeCaptureStore", capture.sink)
    tampered_receipt = _tamper_attempt_receipt(store, receipt, **changed)

    with pytest.raises(ResponseContractError, match="pinned provider contract"):
        replay_stats_packets(
            store,
            tampered_receipt,
            _LegacyEndpoint,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=7,
        )


def test_replay_rejects_source_receipt_substitution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response(
            {"resultSets": [{"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]}]}
        ),
    )
    capture = _capture_contract(tmp_path)
    online = fetch_stats_packets(
        _LegacyEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=7,
    )
    receipt = cast("str", online[0].response_receipt_sha256)
    recorded = capture.sink.load_recorded_attempt(receipt)
    source = SimpleNamespace(
        load_recorded_attempt=lambda _digest: replace(recorded, receipt_sha256="1" * 64)
    )

    with pytest.raises(ResponseContractError, match="pinned provider contract"):
        replay_stats_packets(
            source,
            receipt,
            _LegacyEndpoint,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=7,
        )


def test_replay_rejects_result_receipt_digest_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_stats_response(
        monkeypatch,
        _stats_response(
            {"resultSets": [{"name": "Stats", "headers": ["ID", "VALUE"], "rowSet": [[1, "one"]]}]}
        ),
    )
    capture = _capture_contract(tmp_path)
    online = fetch_stats_packets(
        _LegacyEndpoint,
        capture=capture,
        endpoint_contract=_LEGACY_CONTRACT,
        item_id=7,
    )
    receipt = cast("str", online[0].response_receipt_sha256)
    store = cast("BronzeCaptureStore", capture.sink)
    recorded = store.load_recorded_attempt(receipt)
    drifted = replace(recorded.result_sets[0], normalized_output_sha256="0" * 64)
    tampered_receipt = _tamper_attempt_receipt(
        store,
        receipt,
        result_sets=[asdict(drifted)],
        result_sets_sha256=result_sets_digest((drifted,)),
    )

    with pytest.raises(ResponseContractError, match="result-set receipts"):
        replay_stats_packets(
            store,
            tampered_receipt,
            _LegacyEndpoint,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=7,
        )


def test_replay_rejects_attempt_without_recorded_body(tmp_path: Path) -> None:
    capture = _capture_contract(tmp_path)
    receipt = capture.sink.record_no_response_attempt(
        context=ParserInputContext(attempt_id="adapter-attempt-1"),
        transport_kind="http_response",
        source_family="stats",
        endpoint_id=_LegacyEndpoint.__name__,
        endpoint_slug=_LegacyEndpoint.endpoint,
        parameters={"ItemID": 7},
        provider_authority_sha256=capture.provider_authority_sha256,
        contract_sha256=capture.endpoint_contract_sha256,
        outcome="transport_failure_no_response",
        failure_class="transport_transient",
        root_exception_class="Timeout",
    )

    with pytest.raises(ExtractionError, match="no replayable parser input"):
        replay_stats_packets(
            capture.sink,
            receipt,
            _LegacyEndpoint,
            endpoint_contract=_LEGACY_CONTRACT,
            item_id=7,
        )
