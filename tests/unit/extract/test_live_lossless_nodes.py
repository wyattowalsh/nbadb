from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import polars as pl
import pytest
from nba_api.library.http import NBAResponse
from nba_api.live.nba.endpoints import BoxScore, Odds, PlayByPlay, ScoreBoard

from nbadb.core.errors import ResponseContractError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    LiveEndpointContract,
    LiveResultSetContract,
    owned_contract_sha256,
    pinned_live_endpoint_contract,
)
from nbadb.extract.bronze import BronzeCaptureStore, BronzeLimits, ParserInputContext
from nbadb.extract.live.endpoints import LivePlayByPlayExtractor
from nbadb.extract.live_lossless import (
    LIVE_LOSSLESS_SCHEMA,
    LIVE_LOSSLESS_STAGING_KEY,
    NbaApiLiveLosslessLanding,
    reconstruct_live_payload,
    validate_live_lossless_frame,
)
from nbadb.extract.nba_api_adapter import (
    NbaApiCaptureContract,
    NbaDbLiveHTTP,
    fetch_live_payloads,
    replay_live_payloads,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def _live_response(payload: object) -> NBAResponse:
    return NBAResponse(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        200,
        "fixture://live-lossless",
    )


def _capture_contract(tmp_path: Path, endpoint_cls: type) -> NbaApiCaptureContract:
    contract = pinned_live_endpoint_contract(endpoint_cls)
    store = BronzeCaptureStore(
        tmp_path / "private" / "bronze",
        public_roots=(tmp_path / "data" / "nbadb",),
        limits=BronzeLimits(
            max_response_bytes=2_000_000,
            max_generation_stored_bytes=4_000_000,
            minimum_free_bytes=1,
        ),
    )
    return NbaApiCaptureContract(
        sink=store,
        context=ParserInputContext(attempt_id="live-lossless-attempt"),
        provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
        endpoint_contract_sha256=owned_contract_sha256(contract),
    )


def _sample_value(sample_types: tuple[str, ...]) -> object:
    preferred = next((item for item in sample_types if item != "null"), "null")
    return {
        "array": [],
        "boolean": True,
        "integer": 1,
        "null": None,
        "number": 1.25,
        "object": {},
        "string": "fixture",
    }[preferred]


def _complete_result_container(
    result_set: LiveResultSetContract,
    contract: LiveEndpointContract,
) -> object:
    children = {
        child.parent_field_name: child
        for child in contract.result_sets
        if child.parent_result_set_name == result_set.name and child.parent_field_name is not None
    }
    scalar_projection = (
        len(result_set.fields) == 1
        and not result_set.fields[0].source_field
        and result_set.fields[0].name == "value"
    )
    if scalar_projection:
        record: object = _sample_value(result_set.fields[0].sample_types)
    else:
        values: dict[str, object] = {}
        for field in result_set.fields:
            child = children.get(field.name)
            values[field.name] = (
                _complete_result_container(child, contract)
                if child is not None
                else _sample_value(field.sample_types)
            )
        for name, child in children.items():
            values.setdefault(name, _complete_result_container(child, contract))
        record = values
    if result_set.container_kind == "nba_api_live_json_array":
        return [record]
    return record


def _complete_endpoint_payload(contract: LiveEndpointContract) -> dict[str, object]:
    roots = {
        result_set.traversal_path[0]: result_set
        for result_set in contract.result_sets
        if result_set.parent_result_set_name is None
    }
    return {
        root_name: _complete_result_container(roots[root_name], contract)
        for root_name in contract.envelope_root_order
    }


@pytest.mark.parametrize(
    ("endpoint_cls", "selection", "kwargs"),
    [
        (BoxScore, {"packet": "game"}, {"game_id": "0022400001"}),
        (Odds, {"packet": "games"}, {}),
        (PlayByPlay, {"packet": "game"}, {"game_id": "0022400001"}),
        (ScoreBoard, {"packet": "scoreboard"}, {}),
    ],
)
def test_every_pinned_live_result_set_has_a_replayable_declaration(
    monkeypatch: pytest.MonkeyPatch,
    endpoint_cls: type,
    selection: dict[str, str],
    kwargs: dict[str, object],
) -> None:
    contract = pinned_live_endpoint_contract(endpoint_cls)
    payload = _complete_endpoint_payload(contract)
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: _live_response(payload),
    )

    result = fetch_live_payloads(
        endpoint_cls,
        selection,
        allow_additive_drift=True,
        **kwargs,
    )

    landing = result.live_lossless_landing
    assert isinstance(landing, NbaApiLiveLosslessLanding)
    assert landing.frame.schema == LIVE_LOSSLESS_SCHEMA
    assert landing.expected_result_set_count == len(contract.result_sets)
    declarations = landing.frame.filter(pl.col("record_kind") == "result_set_declaration")
    assert declarations["result_set_name"].to_list() == [item.name for item in contract.result_sets]
    assert reconstruct_live_payload(landing.frame) == payload


def _required_action(*, additive: bool) -> dict[str, object]:
    action: dict[str, object] = {
        "actionNumber": 1,
        "clock": "PT11M00S",
        "timeActual": "2026-04-17T12:00:00Z",
        "period": 1,
        "periodType": "REGULAR",
        "actionType": "period",
        "qualifiers": [],
        "personId": 9_007_199_254_740_993,
        "x": None,
        "y": 1.25,
        "possession": 0,
        "scoreHome": "0",
        "scoreAway": "0",
        "orderNumber": 1,
        "xLegacy": 0,
        "yLegacy": 0,
        "isFieldGoal": 0,
        "side": None,
        "personIdsFilter": [7, 7],
        "description": "Café 🏀",
    }
    if additive:
        action["futureNode"] = {
            "null": None,
            "emptyObject": {},
            "emptyArray": [],
            "mixed": [True, 9_007_199_254_740_993, 1.25, "δοκιμή"],
        }
    return action


def _adversarial_payload() -> dict[str, object]:
    action = _required_action(additive=True)
    return {
        "meta": {"code": 200},
        "game": {
            "gameId": "0022400001",
            "actions": [action, dict(action)],
            "futureGameField": {"nested": [None, {}, []]},
        },
        "futureEnvelope": {"δοκιμή": "値"},
    }


@pytest.mark.asyncio
async def test_additive_live_drift_is_sanitized_for_wide_and_retained_losslessly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _adversarial_payload()
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: _live_response(payload),
    )
    capture = _capture_contract(tmp_path, PlayByPlay)
    extractor = LivePlayByPlayExtractor()
    extractor.begin_extraction_attempt()
    extractor.set_capture_contract(capture)
    snapshot_at = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)

    wide = await extractor.extract(game_id="0022400001", snapshot_at=snapshot_at)

    assert wide.height == 2
    assert "future_node" not in wide.columns
    assert "futureNode" not in json.loads(wide["payload_json"][0])
    landings = extractor.live_lossless_landing_snapshot()
    assert len(landings) == 1
    landing = landings[0]
    assert landing.reason_codes == ("additive_envelope_root", "additive_field")
    assert landing.response_receipt_sha256 is not None
    assert landing.snapshot_at == snapshot_at
    assert landing.frame["response_receipt_sha256"].unique().to_list() == [
        landing.response_receipt_sha256
    ]
    assert landing.frame["snapshot_at"].unique().to_list() == [snapshot_at]
    assert landing.frame["request_parameters_json"].unique().to_list() == [
        '{"GameID":"0022400001"}'
    ]
    assert reconstruct_live_payload(landing.frame) == payload

    nodes = landing.frame.filter(pl.col("record_kind") == "json_node")
    assert (
        nodes.filter(pl.col("json_path") == '$["game"]["actions"][0]')[
            "result_set_row_ordinal"
        ].item()
        == 0
    )
    assert (
        nodes.filter(pl.col("json_path") == '$["game"]["actions"][1]')[
            "result_set_row_ordinal"
        ].item()
        == 1
    )
    assert (
        nodes.filter(pl.col("json_path") == '$["game"]["actions"][0]["subType"]')[
            "presence_kind"
        ].item()
        == "missing"
    )
    assert (
        nodes.filter(pl.col("json_path") == '$["game"]["actions"][0]["side"]')[
            "presence_kind"
        ].item()
        == "null"
    )
    assert (
        nodes.filter(pl.col("json_path") == '$["game"]["actions"][0]["qualifiers"]')[
            "presence_kind"
        ].item()
        == "empty_array"
    )
    assert (
        nodes.filter(pl.col("json_path") == '$["game"]["actions"][0]["futureNode"]["emptyObject"]')[
            "presence_kind"
        ].item()
        == "empty_object"
    )
    assert (
        nodes.filter(pl.col("json_path") == '$["game"]["actions"][0]["futureNode"]["mixed"][1]')[
            "canonical_json"
        ].item()
        == "9007199254740993"
    )
    assert (
        nodes.filter(pl.col("json_path") == '$["futureEnvelope"]["δοκιμή"]')[
            "canonical_json"
        ].item()
        == '"値"'
    )

    action_zero = nodes.filter(pl.col("parent_json_path") == '$["game"]["actions"][0]').filter(
        pl.col("object_key_ordinal").is_not_null()
    )
    assert action_zero.sort("object_key_ordinal")["object_key"].to_list() == list(
        cast("Mapping[str, object]", cast("list[object]", payload["game"]["actions"])[0])
    )


def test_live_lossless_capture_and_replay_are_receipt_equivalent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _adversarial_payload()
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: _live_response(payload),
    )
    capture = _capture_contract(tmp_path, PlayByPlay)
    online = fetch_live_payloads(
        PlayByPlay,
        {"actions": "game_actions"},
        capture=capture,
        allow_additive_drift=True,
        game_id="0022400001",
    )
    receipt = cast("str", online.response_receipt_sha256)

    def _transport_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("lossless replay must not perform transport")

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _transport_forbidden)
    replayed = replay_live_payloads(
        capture.sink,
        receipt,
        PlayByPlay,
        {"actions": "game_actions"},
        allow_additive_drift=True,
        game_id="0022400001",
    )

    assert replayed == online
    assert replayed.live_lossless_landing is not None
    assert online.live_lossless_landing is not None
    assert replayed.live_lossless_landing.frame.equals(online.live_lossless_landing.frame)
    assert reconstruct_live_payload(replayed.live_lossless_landing.frame) == payload
    assert json.loads(capture.sink.replay_parser_input(receipt)) == payload


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing_required", "omitted required fields"),
        ("wrong_type", "value type differs"),
    ],
)
def test_additive_mode_does_not_turn_contract_failures_into_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    action = _required_action(additive=True)
    if mutation == "missing_required":
        del action["clock"]
    else:
        action["clock"] = {"not": "a string"}
    payload = {
        "meta": {"code": 200},
        "game": {"gameId": "0022400001", "actions": [action]},
    }
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: _live_response(payload),
    )
    capture = _capture_contract(tmp_path, PlayByPlay)

    with pytest.raises(ResponseContractError, match=error):
        fetch_live_payloads(
            PlayByPlay,
            {"actions": "game_actions"},
            capture=capture,
            allow_additive_drift=True,
            game_id="0022400001",
        )

    snapshot = capture.receipt_snapshot()
    assert snapshot.successful_response_ordinals == ()
    assert len(snapshot.receipt_sha256s) == 1


def test_live_lossless_frame_rejects_receipt_and_tree_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = pinned_live_endpoint_contract(PlayByPlay)
    payload = _complete_endpoint_payload(contract)
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda _self, **_kwargs: _live_response(payload),
    )
    result = fetch_live_payloads(
        PlayByPlay,
        {"game": "game"},
        allow_additive_drift=True,
        game_id="0022400001",
    )
    landing = cast("NbaApiLiveLosslessLanding", result.live_lossless_landing)

    bad_receipt = landing.frame.with_columns(
        pl.when(pl.col("node_ordinal") == 0)
        .then(pl.lit("a" * 64))
        .otherwise(pl.col("response_receipt_sha256"))
        .alias("response_receipt_sha256")
    )
    with pytest.raises(ResponseContractError, match="unbound.*receipt"):
        validate_live_lossless_frame(
            bad_receipt,
            expected_result_set_count=landing.expected_result_set_count,
        )

    tampered_parent = landing.frame.with_columns(
        pl.when(pl.col("node_ordinal") == 1)
        .then(pl.lit(99, dtype=pl.Int64))
        .otherwise(pl.col("parent_node_ordinal"))
        .alias("parent_node_ordinal")
    )
    with pytest.raises(ResponseContractError, match="parent node"):
        validate_live_lossless_frame(
            tampered_parent,
            expected_result_set_count=landing.expected_result_set_count,
        )


def test_live_lossless_route_is_explicitly_separate_from_stats_fallback() -> None:
    assert LIVE_LOSSLESS_STAGING_KEY == "stg_nba_api_live_lossless_nodes"
    assert len(LIVE_LOSSLESS_SCHEMA) == 29
