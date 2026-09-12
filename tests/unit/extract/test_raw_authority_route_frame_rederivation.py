from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

import polars as pl
import pytest
from nba_api.library.http import NBAResponse
from nba_api.live.nba.endpoints import BoxScore, Odds, PlayByPlay, ScoreBoard

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.errors import ResponseContractError
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    LiveEndpointContract,
    LiveResultSetContract,
    owned_contract_sha256,
    pinned_live_endpoint_contract,
    pinned_static_dataset_contract,
)
from nbadb.extract.landing_projection import project_static_landing_frame
from nbadb.extract.live.endpoints import (
    LiveBoxScoreExtractor,
    LiveOddsExtractor,
    LivePlayByPlayExtractor,
    LiveScoreBoardExtractor,
)
from nbadb.extract.live_lossless import LIVE_LOSSLESS_SCHEMA, LIVE_LOSSLESS_STAGING_KEY
from nbadb.extract.nba_api_adapter import (
    NbaDbLiveHTTP,
    RawAuthorityRouteFrameDerivation,
    UpstreamTransientHttpError,
    fetch_static_packet,
    rederive_raw_authority_route_frames,
)
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    frame_content_hash,
    frame_schema_hash,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_SNAPSHOT_AT = datetime(2026, 4, 17, 12, 30, tzinfo=UTC)
_GAME_ID = "0022400001"
_RECEIPT = "a" * 64
_PROVIDER = expected_nba_api_provider_authority()["authority_sha256"]

_STATIC_DATASETS = (
    "static_players",
    "static_teams",
    "static_wnba_players",
    "static_wnba_teams",
)
_LIVE_CASES = (
    ("live_score_board", ScoreBoard, LiveScoreBoardExtractor, {}),
    ("live_odds", Odds, LiveOddsExtractor, {}),
    ("live_play_by_play", PlayByPlay, LivePlayByPlayExtractor, {"game_id": _GAME_ID}),
    ("live_box_score", BoxScore, LiveBoxScoreExtractor, {"game_id": _GAME_ID}),
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
    return [record] if result_set.container_kind == "nba_api_live_json_array" else record


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


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fixed_routes(endpoint_name: str) -> tuple[object, ...]:
    return tuple(
        sorted(
            (
                route
                for route in staging_route_contract_bundle().routes
                if route.endpoint_name == endpoint_name
            ),
            key=lambda route: route.ordinal,
        )
    )


def _static_args(dataset_id: str) -> dict[str, object]:
    contract = pinned_static_dataset_contract(dataset_id)
    routes = _fixed_routes(dataset_id)
    return {
        "source_family": "static",
        "endpoint_name": dataset_id,
        "endpoint_id": dataset_id,
        "selected_route_ids": tuple(route.route_id for route in routes),
        "parser_input": None,
        "safe_parameters_json": "{}",
        "provider_authority_sha256": _PROVIDER,
        "endpoint_contract_sha256_value": owned_contract_sha256(contract),
        "capture_response_receipt_sha256": _RECEIPT,
        "live_snapshot_at": None,
    }


def _live_args(
    endpoint_name: str,
    endpoint_cls: type,
    params: Mapping[str, object],
    *,
    payload: object | None = None,
) -> dict[str, object]:
    contract = pinned_live_endpoint_contract(endpoint_cls)
    fixed_routes = _fixed_routes(endpoint_name)
    conditional = f"{endpoint_name}:{LIVE_LOSSLESS_STAGING_KEY}:{len(contract.result_sets)}"
    body = _complete_endpoint_payload(contract) if payload is None else payload
    return {
        "source_family": "live",
        "endpoint_name": endpoint_name,
        "endpoint_id": contract.endpoint_id,
        "selected_route_ids": tuple(
            sorted((*tuple(route.route_id for route in fixed_routes), conditional))
        ),
        "parser_input": _canonical_json(body).encode("utf-8"),
        "safe_parameters_json": _canonical_json(dict(params)),
        "provider_authority_sha256": _PROVIDER,
        "endpoint_contract_sha256_value": owned_contract_sha256(contract),
        "capture_response_receipt_sha256": _RECEIPT,
        "live_snapshot_at": _SNAPSHOT_AT,
    }


def _derive(args: Mapping[str, object]) -> tuple[RawAuthorityRouteFrameDerivation, ...]:
    return rederive_raw_authority_route_frames(**cast("Any", dict(args)))


@pytest.mark.parametrize("dataset_id", _STATIC_DATASETS)
def test_all_static_routes_match_installed_projection_and_arrow_contract(dataset_id: str) -> None:
    (derived,) = _derive(_static_args(dataset_id))
    expected = project_static_landing_frame(dataset_id, fetch_static_packet(dataset_id).frame)
    (route,) = _fixed_routes(dataset_id)

    assert derived.route_id == route.route_id
    assert derived.staging_key == route.staging_key
    assert derived.route_contract_sha256 == route.contract_sha256
    assert derived.source_result_ordinals == (0,)
    assert derived.frame.equals(expected)
    assert derived.row_count == expected.height
    assert derived.canonical_frame_format == CANONICAL_FRAME_FORMAT
    assert derived.frame_content_hash_contract == FRAME_CONTENT_HASH_CONTRACT
    assert derived.frame_schema_hash_contract == FRAME_SCHEMA_HASH_CONTRACT
    assert derived.frame_content_sha256 == frame_content_hash(expected)
    assert derived.frame_schema_sha256 == frame_schema_hash(expected)


@pytest.mark.parametrize("dataset_id", _STATIC_DATASETS)
def test_static_installed_row_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    dataset_id: str,
) -> None:
    import nbadb.extract.nba_api_adapter as adapter

    contract = pinned_static_dataset_contract(dataset_id)
    rows = adapter._static_source_rows(contract)
    rows[0] = [*rows[0]]
    rows[0][0] = cast("int", rows[0][0]) + 1
    monkeypatch.setattr(adapter, "_static_source_rows", lambda _contract: rows)

    with pytest.raises(ResponseContractError):
        _derive(_static_args(dataset_id))


@pytest.mark.parametrize(
    ("update", "error"),
    [
        ({"parser_input": b"{}"}, "static route-frame reconstruction"),
        ({"safe_parameters_json": '{"game_id":"001"}'}, "static route-frame reconstruction"),
        ({"live_snapshot_at": _SNAPSHOT_AT}, "static route-frame reconstruction"),
        ({"selected_route_ids": ("static_players:stg_static_players:9",)}, "route closure"),
        ({"capture_response_receipt_sha256": "0"}, "capture receipt"),
        ({"provider_authority_sha256": "f" * 64}, "foreign provider"),
    ],
)
def test_static_identity_mutations_fail_closed(update: dict[str, object], error: str) -> None:
    args = _static_args("static_players")
    args.update(update)
    with pytest.raises(ResponseContractError, match=error):
        _derive(args)


async def _production_frames(
    endpoint_name: str,
    extractor_cls: type,
    params: Mapping[str, object],
) -> list[pl.DataFrame]:
    extractor = extractor_cls()
    kwargs = {**dict(params), "snapshot_at": _SNAPSHOT_AT}
    if endpoint_name == "live_box_score":
        return await extractor.extract_all(**kwargs)
    return [await extractor.extract(**kwargs)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("endpoint_name", "endpoint_cls", "extractor_cls", "params"), _LIVE_CASES)
async def test_all_live_routes_match_production_and_never_reenter_transport(
    monkeypatch: pytest.MonkeyPatch,
    endpoint_name: str,
    endpoint_cls: type,
    extractor_cls: type,
    params: dict[str, object],
) -> None:
    contract = pinned_live_endpoint_contract(endpoint_cls)
    payload = _complete_endpoint_payload(contract)
    parser_input = _canonical_json(payload)
    calls = 0

    def _send(_self: object, **_kwargs: object) -> NBAResponse:
        nonlocal calls
        calls += 1
        return NBAResponse(parser_input, 200, "fixture://live-route-production")

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _send)
    production = await _production_frames(endpoint_name, extractor_cls, params)
    assert calls == 1

    def _forbid_transport(_self: object, **_kwargs: object) -> NBAResponse:
        raise AssertionError("raw route-frame replay attempted provider transport")

    monkeypatch.setattr(NbaDbLiveHTTP, "send_api_request", _forbid_transport)
    derived = _derive(_live_args(endpoint_name, endpoint_cls, params, payload=payload))
    fixed_routes = _fixed_routes(endpoint_name)

    assert len(derived) == len(fixed_routes) + 1
    assert [item.route_id for item in derived[:-1]] == [route.route_id for route in fixed_routes]
    assert [
        item.frame.equals(expected) for item, expected in zip(derived[:-1], production, strict=True)
    ] == [True] * len(production)
    assert derived[-1].route_id == (
        f"{endpoint_name}:{LIVE_LOSSLESS_STAGING_KEY}:{len(contract.result_sets)}"
    )
    assert derived[-1].staging_key == LIVE_LOSSLESS_STAGING_KEY
    assert derived[-1].source_result_ordinals == tuple(range(len(contract.result_sets)))
    assert derived[-1].frame.schema == LIVE_LOSSLESS_SCHEMA
    assert set(derived[-1].frame["response_receipt_sha256"].to_list()) == {_RECEIPT}
    assert all(item.frame_content_sha256 == frame_content_hash(item.frame) for item in derived)
    assert all(item.frame_schema_sha256 == frame_schema_hash(item.frame) for item in derived)
    assert calls == 1


@pytest.mark.asyncio
async def test_live_present_empty_wide_still_emits_complete_lossless_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = pinned_live_endpoint_contract(PlayByPlay)
    payload = _complete_endpoint_payload(contract)
    cast("dict[str, object]", payload["game"])["actions"] = []
    parser_input = _canonical_json(payload)
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda *_args, **_kwargs: NBAResponse(parser_input, 200, "fixture://empty-live-route"),
    )
    (production,) = await _production_frames(
        "live_play_by_play",
        LivePlayByPlayExtractor,
        {"game_id": _GAME_ID},
    )
    monkeypatch.setattr(
        NbaDbLiveHTTP,
        "send_api_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport attempted")),
    )

    ordinary, lossless = _derive(
        _live_args("live_play_by_play", PlayByPlay, {"game_id": _GAME_ID}, payload=payload)
    )

    assert ordinary.row_count == 0
    assert ordinary.frame.equals(production)
    assert ordinary.frame.columns == [
        "game_id",
        "action_number",
        "snapshot_at",
        "snapshot_date",
        "source_endpoint",
        "payload_json",
    ]
    assert lossless.row_count > 0
    assert lossless.frame.schema == LIVE_LOSSLESS_SCHEMA


def test_live_additive_shape_is_sanitized_wide_and_retained_losslessly() -> None:
    contract = pinned_live_endpoint_contract(PlayByPlay)
    payload = _complete_endpoint_payload(contract)
    game = cast("dict[str, object]", payload["game"])
    action = cast("list[dict[str, object]]", game["actions"])[0]
    action["futureNode"] = {"unicode": "δοκιμή", "mixed": [None, {}, []]}

    ordinary, lossless = _derive(
        _live_args("live_play_by_play", PlayByPlay, {"game_id": _GAME_ID}, payload=payload)
    )

    assert "future_node" not in ordinary.frame.columns
    assert "futureNode" in lossless.frame["object_key"].drop_nulls().to_list()
    assert "additive_field" in lossless.frame["anomaly_codes_json"][0]


@pytest.mark.parametrize(
    ("update", "error"),
    [
        ({"safe_parameters_json": '{"game_id": "0022400001"}'}, "canonical JSON"),
        ({"safe_parameters_json": '{"GameID":"0022400001"}'}, "unknown domain parameter"),
        ({"safe_parameters_json": '{"proxy":"https://example.invalid"}'}, "public-safe"),
        ({"safe_parameters_json": '{"game_id":"001"}'}, "pinned pattern"),
        ({"live_snapshot_at": None}, "aware UTC snapshot"),
        ({"live_snapshot_at": datetime(2026, 4, 17, 12, 30)}, "aware UTC snapshot"),
        (
            {
                "live_snapshot_at": datetime(
                    2026,
                    4,
                    17,
                    12,
                    30,
                    tzinfo=timezone(timedelta(hours=1)),
                )
            },
            "aware UTC snapshot",
        ),
        ({"capture_response_receipt_sha256": "f"}, "capture receipt"),
        ({"endpoint_id": "ScoreBoard"}, "pinned endpoint contract"),
    ],
)
def test_live_identity_parameter_and_snapshot_mutations_fail_closed(
    update: dict[str, object],
    error: str,
) -> None:
    args = _live_args("live_play_by_play", PlayByPlay, {"game_id": _GAME_ID})
    args.update(update)
    with pytest.raises((ResponseContractError, ValueError), match=error):
        _derive(args)


@pytest.mark.parametrize(
    ("parser_input", "error"),
    [
        (b"{", "malformed JSON"),
        (b'{"meta":{"code":200,"code":201},"game":{"actions":[]}}', "duplicate"),
        (b'{"meta":{"code":NaN},"game":{"actions":[]}}', "non-finite"),
    ],
)
def test_live_body_mutations_fail_closed(parser_input: bytes, error: str) -> None:
    args = _live_args("live_play_by_play", PlayByPlay, {"game_id": _GAME_ID})
    args["parser_input"] = parser_input
    with pytest.raises(ResponseContractError, match=error):
        _derive(args)


def test_live_retryable_error_envelope_preserves_failure_classification() -> None:
    args = _live_args("live_play_by_play", PlayByPlay, {"game_id": _GAME_ID})
    args["parser_input"] = b'{"meta":{"code":500},"game":{"actions":[]}}'

    with pytest.raises(UpstreamTransientHttpError, match="JSON error envelope status 500"):
        _derive(args)


def test_live_route_subset_extra_and_reorder_fail_closed() -> None:
    args = _live_args("live_box_score", BoxScore, {"game_id": _GAME_ID})
    routes = cast("tuple[str, ...]", args["selected_route_ids"])
    attacks = (
        routes[:-1],
        tuple(sorted((*routes, "live_box_score:stg_unknown:99"))),
        tuple(reversed(routes)),
    )
    for selected in attacks:
        hostile = dict(args, selected_route_ids=selected)
        with pytest.raises(ResponseContractError, match="route inventory|route closure"):
            _derive(hostile)


def test_route_derivation_rejects_stale_frame_hash_after_tamper() -> None:
    (derived,) = _derive(_static_args("static_players"))
    tampered = derived.frame.with_columns((pl.col("id") + 1).alias("id"))

    with pytest.raises(ResponseContractError, match="Arrow V2"):
        replace(derived, frame=tampered)
