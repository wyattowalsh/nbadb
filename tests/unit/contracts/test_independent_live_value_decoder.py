from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

import nbadb.contracts.independent_live_value_decoder as live_decoder
from nbadb.contracts.independent_live_value_decoder import (
    DecodedLiveFieldCellV1,
    DecodedLiveNodeV1,
    DecodedLiveResponseV1,
    DecodedLiveResultOccurrenceV1,
    DecodedLiveResultSetV1,
    IndependentLiveValueDecoderError,
    decode_live_value_response,
    decode_live_value_rows,
    pinned_live_decoder_contract_identities,
    validate_decoded_live_response,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


_RESOURCE = (
    Path(__file__).parents[3]
    / "src"
    / "nbadb"
    / "contracts"
    / "nba_api_runtime_contract_v1_11_4.json"
)


def _raw_live_contracts() -> dict[str, dict[str, object]]:
    payload = json.loads(_RESOURCE.read_bytes())
    return cast("dict[str, dict[str, object]]", payload["live_contracts"])


def _contract(endpoint_id: str) -> dict[str, object]:
    return _raw_live_contracts()[endpoint_id]


def _sample_value(raw_sample_types: object) -> object:
    sample_types = (
        (cast("str", raw_sample_types),)
        if type(raw_sample_types) is str
        else tuple(cast("list[str]", raw_sample_types))
    )
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
    raw_result_set: Mapping[str, object],
    raw_contract: Mapping[str, object],
) -> object:
    raw_result_sets = cast("list[dict[str, object]]", raw_contract["result_sets"])
    children = {
        cast("str", child["parent_field_name"]): child
        for child in raw_result_sets
        if child["parent_result_set_name"] == raw_result_set["name"]
    }
    raw_fields = cast("list[dict[str, object]]", raw_result_set["fields"])
    scalar_projection = (
        len(raw_fields) == 1
        and raw_fields[0]["source_field"] is False
        and raw_fields[0]["name"] == "value"
    )
    if scalar_projection:
        record: object = _sample_value(raw_fields[0]["sample_type"])
    else:
        record = {
            cast("str", field["name"]): (
                _complete_result_container(children[cast("str", field["name"])], raw_contract)
                if field["name"] in children
                else _sample_value(field["sample_type"])
            )
            for field in raw_fields
        }
    return [record] if raw_result_set["container_kind"] == "nba_api_live_json_array" else record


def _complete_payload(endpoint_id: str) -> dict[str, object]:
    raw_contract = _contract(endpoint_id)
    raw_result_sets = cast("list[dict[str, object]]", raw_contract["result_sets"])
    roots = {
        cast("list[str]", result_set["traversal_path"])[0]: result_set
        for result_set in raw_result_sets
        if result_set["parent_result_set_name"] is None
    }
    return {
        root_name: _complete_result_container(roots[root_name], raw_contract)
        for root_name in cast("list[str]", raw_contract["envelope_root_order"])
    }


def _encode(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _decode(endpoint_id: str, payload: object | None = None):
    raw_contract = _contract(endpoint_id)
    return decode_live_value_response(
        _encode(_complete_payload(endpoint_id) if payload is None else payload),
        endpoint_id=endpoint_id,
        endpoint_contract_sha256=cast("str", raw_contract["contract_sha256"]),
    )


def _reseal_node(
    item: DecodedLiveNodeV1,
    **changes: object,
) -> DecodedLiveNodeV1:
    forged = replace(item)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    object.__setattr__(
        forged,
        "node_sha256",
        live_decoder._canonical_sha256(live_decoder._node_identity(forged)),
    )
    return forged


def _reseal_occurrence(
    item: DecodedLiveResultOccurrenceV1,
    **changes: object,
) -> DecodedLiveResultOccurrenceV1:
    forged = replace(item)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    object.__setattr__(
        forged,
        "occurrence_sha256",
        live_decoder._canonical_sha256(live_decoder._result_occurrence_identity(forged)),
    )
    return forged


def _reseal_cell(
    item: DecodedLiveFieldCellV1,
    **changes: object,
) -> DecodedLiveFieldCellV1:
    forged = replace(item)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    object.__setattr__(
        forged,
        "cell_sha256",
        live_decoder._canonical_sha256(live_decoder._field_cell_identity(forged)),
    )
    return forged


def _reseal_result_set(
    item: DecodedLiveResultSetV1,
    **changes: object,
) -> DecodedLiveResultSetV1:
    forged = replace(item)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    object.__setattr__(
        forged,
        "result_set_sha256",
        live_decoder._canonical_sha256(live_decoder._result_set_identity(forged)),
    )
    return forged


def _reseal_response(
    item: DecodedLiveResponseV1,
    **changes: object,
) -> DecodedLiveResponseV1:
    forged = replace(item)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    object.__setattr__(
        forged,
        "result_sets_sha256",
        live_decoder._canonical_sha256([result.result_set_sha256 for result in forged.result_sets]),
    )
    object.__setattr__(
        forged,
        "result_occurrences_sha256",
        live_decoder._canonical_sha256(
            [occurrence.occurrence_sha256 for occurrence in forged.result_occurrences]
        ),
    )
    object.__setattr__(
        forged,
        "nodes_sha256",
        live_decoder._canonical_sha256([node.node_sha256 for node in forged.nodes]),
    )
    object.__setattr__(
        forged,
        "field_cells_sha256",
        live_decoder._canonical_sha256([cell.cell_sha256 for cell in forged.field_cells]),
    )
    object.__setattr__(
        forged,
        "response_sha256",
        live_decoder._canonical_sha256(live_decoder._response_identity(forged)),
    )
    return forged


@pytest.fixture(scope="module", autouse=True)
def _warm_frozen_contract() -> None:
    assert set(pinned_live_decoder_contract_identities()) == {
        "BoxScore",
        "Odds",
        "PlayByPlay",
        "ScoreBoard",
    }


@pytest.mark.parametrize(
    ("endpoint_id", "result_set_count", "parsed_field_count"),
    [
        ("BoxScore", 14, 276),
        ("Odds", 4, 22),
        ("PlayByPlay", 4, 61),
        ("ScoreBoard", 11, 72),
    ],
)
def test_all_frozen_live_contracts_decode_with_exact_census(
    endpoint_id: str,
    result_set_count: int,
    parsed_field_count: int,
) -> None:
    response = _decode(endpoint_id)
    raw_contract = _contract(endpoint_id)

    assert response.endpoint_id == endpoint_id
    assert response.endpoint_slug == raw_contract["endpoint_slug"]
    assert response.endpoint_contract_sha256 == raw_contract["contract_sha256"]
    assert response.contract_result_set_count == result_set_count
    assert len(response.result_sets) == result_set_count
    assert response.result_occurrence_count == result_set_count
    assert response.field_cell_count == parsed_field_count
    assert sum(item.field_cell_count for item in response.result_sets) == parsed_field_count
    assert tuple(item.ordinal for item in response.result_sets) == tuple(range(result_set_count))
    assert tuple(item.name for item in response.result_sets) == tuple(
        cast("str", item["name"])
        for item in cast("list[dict[str, object]]", raw_contract["result_sets"])
    )
    assert validate_decoded_live_response(response) == response


def test_complete_frozen_census_is_exactly_four_endpoints_33_results_431_fields() -> None:
    responses = tuple(_decode(endpoint_id) for endpoint_id in sorted(_raw_live_contracts()))

    assert sum(item.contract_result_set_count for item in responses) == 33
    assert sum(item.field_cell_count for item in responses) == 431
    assert pinned_live_decoder_contract_identities() == {
        endpoint_id: cast("str", contract["contract_sha256"])
        for endpoint_id, contract in _raw_live_contracts().items()
    }


def test_decoding_is_byte_fixed_point_and_thin_rows_are_exact() -> None:
    payload = _complete_payload("Odds")
    raw = _encode(payload)
    contract_sha256 = cast("str", _contract("Odds")["contract_sha256"])

    first = decode_live_value_response(
        raw,
        endpoint_id="Odds",
        endpoint_contract_sha256=contract_sha256,
    )
    second = decode_live_value_response(
        raw,
        endpoint_id="Odds",
        endpoint_contract_sha256=contract_sha256,
    )

    assert first == second
    assert first.response_sha256 == second.response_sha256
    assert first.to_canonical_bytes() == second.to_canonical_bytes()
    assert (
        decode_live_value_rows(
            raw,
            endpoint_id="Odds",
            endpoint_contract_sha256=contract_sha256,
        )
        == first.nodes
    )


def test_unicode_mixed_values_duplicates_and_scalar_cells_are_lossless() -> None:
    payload = _complete_payload("PlayByPlay")
    game = cast("dict[str, object]", payload["game"])
    actions = cast("list[object]", game["actions"])
    action = cast("dict[str, object]", actions[0])
    action["description"] = "Café 🏀 δοκιμή 値"
    action["side"] = None
    action["qualifiers"] = []
    action["personIdsFilter"] = [7, 7]
    action["futureNode"] = {
        "null": None,
        "emptyObject": {},
        "emptyArray": [],
        "mixed": [True, 9_007_199_254_740_993, 1.25, "δοκιμή"],
    }
    actions.append(copy.deepcopy(action))

    response = _decode("PlayByPlay", payload)

    assert response.anomaly_codes == ("additive_field",)
    assert response.null_node_count >= 4
    assert response.present_empty_node_count >= 6
    unicode_node = next(
        item
        for item in response.nodes
        if item.json_path == '$["game"]["actions"][0]["description"]'
    )
    assert unicode_node.value_kind == "string"
    assert unicode_node.canonical_json == '"Café 🏀 δοκιμή 値"'
    large_integer = next(
        item
        for item in response.nodes
        if item.json_path == '$["game"]["actions"][0]["futureNode"]["mixed"][1]'
    )
    assert large_integer.value_kind == "integer"
    assert large_integer.canonical_json == "9007199254740993"

    scalar_result = next(
        item for item in response.result_sets if item.name == "game_actions_personidsfilter"
    )
    assert scalar_result.container_count == 2
    assert scalar_result.parent_observation_count == 2
    assert scalar_result.result_occurrence_count == 2
    assert scalar_result.row_count == 4
    assert scalar_result.value_cell_count == 4
    assert scalar_result.field_cell_count == 4
    action_result = next(item for item in response.result_sets if item.name == "game_actions")
    assert action_result.value_cell_count == action_result.row_count * len(
        action_result.ordered_headers
    )
    assert action_result.field_cell_count > action_result.value_cell_count
    assert [
        item.canonical_json
        for item in response.field_cells
        if item.owner_result_set_name == "game_actions_personidsfilter"
    ] == ["7", "7", "7", "7"]
    scalar_occurrences = tuple(
        item
        for item in response.result_occurrences
        if item.result_set_name == "game_actions_personidsfilter"
    )
    assert tuple(item.occurrence_ordinal for item in scalar_occurrences) == (0, 1)
    assert scalar_occurrences[0].value_sha256 == scalar_occurrences[1].value_sha256
    assert scalar_occurrences[0].json_path != scalar_occurrences[1].json_path


def test_missing_nested_result_uses_child_context_and_parent_field_ownership() -> None:
    payload = _complete_payload("ScoreBoard")
    scoreboard = cast("dict[str, object]", payload["scoreboard"])
    game = cast("dict[str, object]", cast("list[object]", scoreboard["games"])[0])
    del game["gameLeaders"]

    response = _decode("ScoreBoard", payload)
    missing = next(
        item
        for item in response.nodes
        if item.json_path == '$["scoreboard"]["games"][0]["gameLeaders"]'
    )
    field_cell = next(
        item for item in response.field_cells if item.node_ordinal == missing.node_ordinal
    )
    result = next(
        item for item in response.result_sets if item.name == "scoreboard_games_gameleaders"
    )

    assert missing.presence_kind == "missing"
    assert missing.value_kind == "missing"
    assert missing.result_set_name == "scoreboard_games_gameleaders"
    assert missing.result_set_ordinal == 7
    assert missing.result_set_occurrence == 0
    assert missing.result_set_row_ordinal is None
    assert missing.container_kind == "nba_api_live_json_object"
    assert field_cell.owner_result_set_name == "scoreboard_games"
    assert field_cell.owner_result_set_ordinal == 2
    assert field_cell.context_result_set_name == "scoreboard_games_gameleaders"
    assert field_cell.context_result_set_ordinal == 7
    assert field_cell.field_name == "gameLeaders"
    assert result.presence == "missing"
    assert result.container_count == 0
    assert result.missing_count == 1
    assert result.null_count == 0
    assert result.parent_observation_count == 1
    assert result.result_occurrence_count == 1
    assert result.row_count == 0


def test_null_empty_array_empty_object_and_empty_parent_are_distinct() -> None:
    null_payload = _complete_payload("ScoreBoard")
    null_scoreboard = cast("dict[str, object]", null_payload["scoreboard"])
    null_game = cast("dict[str, object]", cast("list[object]", null_scoreboard["games"])[0])
    null_game["pbOdds"] = None
    null_response = _decode("ScoreBoard", null_payload)
    null_result = next(item for item in null_response.result_sets if item.name.endswith("pbodds"))
    assert null_result.presence == "null"
    assert null_result.null_count == 1
    assert null_result.result_occurrence_count == 1

    array_payload = _complete_payload("ScoreBoard")
    array_scoreboard = cast("dict[str, object]", array_payload["scoreboard"])
    array_game = cast("dict[str, object]", cast("list[object]", array_scoreboard["games"])[0])
    home_team = cast("dict[str, object]", array_game["homeTeam"])
    home_team["periods"] = []
    array_response = _decode("ScoreBoard", array_payload)
    array_result = next(
        item
        for item in array_response.result_sets
        if item.name == "scoreboard_games_hometeam_periods"
    )
    assert array_result.presence == "empty_array"
    assert array_result.container_count == 1
    assert array_result.row_count == 0
    assert array_result.result_occurrence_count == 1

    object_payload = _complete_payload("ScoreBoard")
    object_scoreboard = cast("dict[str, object]", object_payload["scoreboard"])
    object_game = cast("dict[str, object]", cast("list[object]", object_scoreboard["games"])[0])
    object_game["gameLeaders"] = {}
    object_response = _decode("ScoreBoard", object_payload)
    object_result = next(
        item for item in object_response.result_sets if item.name == "scoreboard_games_gameleaders"
    )
    assert object_result.presence == "present"
    assert object_result.container_count == 1
    assert object_result.row_count == 1
    assert object_result.field_cell_count == 2
    assert any(
        item.presence_kind == "empty_object"
        and item.result_set_name == "scoreboard_games_gameleaders"
        for item in object_response.nodes
    )

    parent_empty_payload = _complete_payload("ScoreBoard")
    parent_empty_scoreboard = cast("dict[str, object]", parent_empty_payload["scoreboard"])
    parent_empty_scoreboard["games"] = []
    parent_empty_response = _decode("ScoreBoard", parent_empty_payload)
    child_results = tuple(
        item
        for item in parent_empty_response.result_sets
        if item.parent_result_set_name == "scoreboard_games"
    )
    assert child_results
    assert all(item.presence == "not_observed_parent_empty" for item in child_results)
    assert all(item.parent_observation_count == 0 for item in child_results)
    assert all(item.result_occurrence_count == 0 for item in child_results)


def test_mixed_missing_and_null_nested_parents_are_losslessly_distinct() -> None:
    from nbadb.core.nba_api_runtime_contract import pinned_live_contracts
    from nbadb.extract import nba_api_adapter

    payload = _complete_payload("ScoreBoard")
    scoreboard = cast("dict[str, object]", payload["scoreboard"])
    games = cast("list[dict[str, object]]", scoreboard["games"])
    games.append(copy.deepcopy(games[0]))
    del games[0]["pbOdds"]
    games[1]["pbOdds"] = None

    response = _decode("ScoreBoard", payload)
    result = next(item for item in response.result_sets if item.name.endswith("pbodds"))
    occurrences = tuple(
        item for item in response.result_occurrences if item.result_set_name == result.name
    )

    assert result.presence == "mixed_absent"
    assert result.container_count == 0
    assert result.missing_count == 1
    assert result.null_count == 1
    assert result.parent_observation_count == 2
    assert result.result_occurrence_count == 2
    assert result.row_count == 0
    assert tuple(item.presence_kind for item in occurrences) == ("missing", "null")
    assert tuple(item.row_count for item in occurrences) == (0, 0)
    assert result.parent_occurrence_states_sha256 == live_decoder._canonical_sha256(
        ["missing", "null"]
    )

    production, anomaly_codes = nba_api_adapter._validate_live_envelope(
        pinned_live_contracts()["ScoreBoard"],
        payload,
        allow_additive_drift=True,
    )
    production_result = production[result.name]
    assert anomaly_codes == response.anomaly_codes == ()
    assert len(production_result.containers) == result.container_count
    assert production_result.missing_count == result.missing_count
    assert production_result.null_count == result.null_count
    assert production_result.parent_occurrence_states_sha256 == (
        result.parent_occurrence_states_sha256
    )
    assert production_result.normalized_output_sha256 == result.normalized_output_sha256
    assert (
        validate_decoded_live_response(response).to_canonical_bytes()
        == response.to_canonical_bytes()
    )
    assert _decode("ScoreBoard", payload).to_canonical_bytes() == response.to_canonical_bytes()


def test_fully_resealed_mixed_absent_presence_tampering_is_rejected() -> None:
    payload = _complete_payload("ScoreBoard")
    scoreboard = cast("dict[str, object]", payload["scoreboard"])
    games = cast("list[dict[str, object]]", scoreboard["games"])
    games.append(copy.deepcopy(games[0]))
    del games[0]["pbOdds"]
    games[1]["pbOdds"] = None
    response = _decode("ScoreBoard", payload)
    target = next(item for item in response.result_sets if item.name.endswith("pbodds"))
    forged_target = _reseal_result_set(target, presence="missing")
    forged_results = tuple(
        forged_target if item.ordinal == target.ordinal else item for item in response.result_sets
    )
    forged = _reseal_response(response, result_sets=forged_results)

    with pytest.raises(IndependentLiveValueDecoderError, match="exact denominators"):
        validate_decoded_live_response(forged)


def test_envelope_and_object_order_are_preserved_and_reason_coded() -> None:
    payload = _complete_payload("ScoreBoard")
    reordered = {
        "scoreboard": payload["scoreboard"],
        "meta": payload["meta"],
        "futureEnvelope": {"値": "δοκιμή"},
    }

    response = _decode("ScoreBoard", reordered)

    assert response.anomaly_codes == (
        "additive_envelope_root",
        "reordered_envelope_root",
    )
    assert response.nodes[1].object_key == "scoreboard"
    future = next(item for item in response.nodes if item.json_path == '$["futureEnvelope"]["値"]')
    assert future.canonical_json == '"δοκιμή"'


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        (b'{"meta":{},"meta":{},"game":{}}', "duplicate JSON object keys"),
        (b'{"meta":{"version":NaN},"game":{}}', "non-finite"),
        (b'{"meta":{"version":Infinity},"game":{}}', "non-finite"),
        (b'{"meta":{"version":9223372036854775808},"game":{}}', "signed 64-bit"),
        (
            b'{"meta":{"version":11111111111111111111111111111111111111111111111111111111111111111},"game":{}}',
            "number token",
        ),
        (b'{"meta":{},"game":{"gameId":"\\ud800"}}', "bounded valid UTF-8 JSON"),
        (b'{"meta":{},"game":{}}\xff', "bounded valid UTF-8 JSON"),
        (b"[]", "root must be an object"),
        (b'{"meta":{},"game":', "lexical structure"),
    ],
)
def test_malformed_duplicate_nonfinite_huge_number_and_unicode_fail_closed(
    raw: bytes,
    error: str,
) -> None:
    with pytest.raises(IndependentLiveValueDecoderError, match=error):
        decode_live_value_response(
            raw,
            endpoint_id="PlayByPlay",
            endpoint_contract_sha256=cast("str", _contract("PlayByPlay")["contract_sha256"]),
        )


def test_deep_json_is_rejected_before_recursive_decoding() -> None:
    raw = (
        b'{"meta":{},"game":{},"future":'
        + (b"[" * (live_decoder.MAX_JSON_DEPTH + 1))
        + b"0"
        + (b"]" * (live_decoder.MAX_JSON_DEPTH + 1))
        + b"}"
    )

    with pytest.raises(IndependentLiveValueDecoderError, match="depth exceeds"):
        decode_live_value_response(
            raw,
            endpoint_id="PlayByPlay",
            endpoint_contract_sha256=cast("str", _contract("PlayByPlay")["contract_sha256"]),
        )


@pytest.mark.parametrize(
    ("endpoint_id", "digest", "error"),
    [
        ("ForeignLive", "0" * 64, "differs from the exact frozen contract"),
        ("ScoreBoard", "0" * 64, "differs from the exact frozen contract"),
        ("ScoreBoard", "A" * 64, "lowercase full SHA-256"),
        (cast("str", True), "0" * 64, "nonempty exact string"),
    ],
)
def test_foreign_endpoint_or_contract_identity_fails_closed(
    endpoint_id: str,
    digest: str,
    error: str,
) -> None:
    with pytest.raises(IndependentLiveValueDecoderError, match=error):
        decode_live_value_response(
            _encode(_complete_payload("ScoreBoard")),
            endpoint_id=endpoint_id,
            endpoint_contract_sha256=digest,
        )


def test_missing_root_wrong_container_required_missing_and_wrong_type_fail_closed() -> None:
    digest = cast("str", _contract("PlayByPlay")["contract_sha256"])
    payload = _complete_payload("PlayByPlay")
    del payload["meta"]
    with pytest.raises(IndependentLiveValueDecoderError, match="required envelope root"):
        decode_live_value_response(
            _encode(payload),
            endpoint_id="PlayByPlay",
            endpoint_contract_sha256=digest,
        )

    payload = _complete_payload("PlayByPlay")
    payload["meta"] = []
    with pytest.raises(IndependentLiveValueDecoderError, match="must be an object"):
        decode_live_value_response(
            _encode(payload),
            endpoint_id="PlayByPlay",
            endpoint_contract_sha256=digest,
        )

    payload = _complete_payload("PlayByPlay")
    action = cast(
        "dict[str, object]",
        cast("list[object]", cast("dict[str, object]", payload["game"])["actions"])[0],
    )
    del action["personIdsFilter"]
    with pytest.raises(IndependentLiveValueDecoderError, match="required fields"):
        decode_live_value_response(
            _encode(payload),
            endpoint_id="PlayByPlay",
            endpoint_contract_sha256=digest,
        )

    payload = _complete_payload("PlayByPlay")
    action = cast(
        "dict[str, object]",
        cast("list[object]", cast("dict[str, object]", payload["game"])["actions"])[0],
    )
    action["clock"] = {"foreign": True}
    with pytest.raises(IndependentLiveValueDecoderError, match="value type differs"):
        decode_live_value_response(
            _encode(payload),
            endpoint_id="PlayByPlay",
            endpoint_contract_sha256=digest,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"message": "false success"},
        {"Message": "false success"},
        {"error": {"code": "bad"}},
        {"statusCode": 500},
        {"status": 429},
        {"code": 503},
    ],
)
def test_error_envelopes_reject_even_when_live_roots_are_otherwise_valid(
    mutation: dict[str, object],
) -> None:
    payload = _complete_payload("ScoreBoard")
    payload.update(mutation)

    with pytest.raises(IndependentLiveValueDecoderError, match="error"):
        _decode("ScoreBoard", payload)


@pytest.mark.parametrize(
    ("limit_name", "limit", "error"),
    [
        ("MAX_PARSER_INPUT_BYTES", 32, "byte length"),
        ("MAX_JSON_NODES", 8, "node count"),
        ("MAX_JSON_CONTAINER_ITEMS", 8, "container item count"),
        ("MAX_JSON_TOTAL_STRING_BYTES", 8, "cumulative string bytes"),
        ("MAX_LIVE_RESULT_OCCURRENCES", 1, "occurrence count"),
        ("MAX_LIVE_FIELD_CELLS", 1, "field-cell count"),
        ("MAX_TOTAL_VALUE_DIGEST_BYTES", 32, "cumulative canonical value bytes"),
    ],
)
def test_preallocation_and_cumulative_resource_limits_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit: int,
    error: str,
) -> None:
    monkeypatch.setattr(live_decoder, limit_name, limit)

    with pytest.raises(IndependentLiveValueDecoderError, match=error):
        _decode("ScoreBoard")


def test_public_dtos_are_immutable_detached_and_strictly_revalidated() -> None:
    response = _decode("Odds")
    original_path = response.nodes[0].json_path
    detached = response.to_dict()
    cast("list[dict[str, object]]", detached["nodes"])[0]["json_path"] = '$["forged"]'

    assert response.nodes[0].json_path == original_path
    with pytest.raises(AttributeError):
        response.nodes[0].json_path = '$["forged"]'  # type: ignore[misc]

    forged_response = replace(response)
    object.__setattr__(forged_response, "node_count", True)
    with pytest.raises(IndependentLiveValueDecoderError, match="exact integer"):
        validate_decoded_live_response(forged_response)
    with pytest.raises(IndependentLiveValueDecoderError, match="exact integer"):
        forged_response.to_canonical_bytes()

    forged_node = replace(response.nodes[0])
    object.__setattr__(forged_node, "json_path", '$["forged"]')
    forged_nested = replace(response)
    object.__setattr__(
        forged_nested,
        "nodes",
        (forged_node, *response.nodes[1:]),
    )
    with pytest.raises(IndependentLiveValueDecoderError, match="node digest"):
        validate_decoded_live_response(forged_nested)


@pytest.mark.parametrize("target", ["node", "occurrence", "cell", "result", "response"])
def test_resealed_field_tampering_is_rejected(target: str) -> None:
    response = _decode("BoxScore")

    with pytest.raises(IndependentLiveValueDecoderError):
        if target == "node":
            replace(response.nodes[1], depth=response.nodes[1].depth + 1)
        elif target == "occurrence":
            replace(response.result_occurrences[0], row_count=99)
        elif target == "cell":
            replace(response.field_cells[0], field_name="FORGED")
        elif target == "result":
            replace(response.result_sets[0], row_count=99)
        else:
            replace(response, endpoint_slug="foreign")


@pytest.mark.parametrize("edge", ["path", "object_ordinal", "array_ordinal"])
def test_fully_resealed_node_edge_forgery_is_rejected(edge: str) -> None:
    payload = _complete_payload("ScoreBoard")
    payload["futureEnvelope"] = [1]
    response = _decode("ScoreBoard", payload)
    if edge == "array_ordinal":
        target = next(item for item in response.nodes if item.json_path == '$["futureEnvelope"][0]')
        forged_node = _reseal_node(target, array_ordinal=99)
    else:
        target = next(item for item in response.nodes if item.json_path == '$["futureEnvelope"]')
        forged_node = _reseal_node(
            target,
            **({"json_path": '$["forged"]'} if edge == "path" else {"object_key_ordinal": 99}),
        )
    nodes = tuple(
        forged_node if item.node_ordinal == target.node_ordinal else item for item in response.nodes
    )
    forged = _reseal_response(response, nodes=nodes)

    with pytest.raises(
        IndependentLiveValueDecoderError,
        match="(parent path|object edge|array edge|child ordinals)",
    ):
        validate_decoded_live_response(forged)


def test_fully_resealed_occurrence_row_count_forgery_is_rejected() -> None:
    response = _decode("Odds")
    target = response.result_occurrences[0]
    forged_occurrence = _reseal_occurrence(target, row_count=target.row_count + 1)
    occurrences = (
        forged_occurrence,
        *response.result_occurrences[1:],
    )
    forged = _reseal_response(response, result_occurrences=occurrences)

    with pytest.raises(IndependentLiveValueDecoderError, match="reconstructed projection"):
        validate_decoded_live_response(forged)


@pytest.mark.parametrize(
    "changes",
    [
        {"row_count": 2, "value_cell_count": 12},
        {"container_count": 2},
        {"missing_count": 1},
        {"null_count": 1},
        {"presence": "missing"},
        {"parent_observation_count": 2, "result_occurrence_count": 2},
        {"parent_occurrence_states_sha256": "0" * 64},
    ],
)
def test_fully_resealed_result_denominator_and_state_forgery_is_rejected(
    changes: dict[str, object],
) -> None:
    response = _decode("Odds")
    target = response.result_sets[0]
    forged_result = _reseal_result_set(target, **changes)
    results = (forged_result, *response.result_sets[1:])
    forged = _reseal_response(response, result_sets=results)

    with pytest.raises(
        IndependentLiveValueDecoderError,
        match=(
            "(reconstructed|denominators differ|denominators are inconsistent|exact denominators)"
        ),
    ):
        validate_decoded_live_response(forged)


@pytest.mark.parametrize(
    "changes",
    [
        {"owner_result_set_occurrence": 1},
        {"context_result_set_occurrence": 1},
        {"owner_row_ordinal": 99},
    ],
)
def test_fully_resealed_cell_occurrence_and_row_binding_forgery_is_rejected(
    changes: dict[str, object],
) -> None:
    response = _decode("Odds")
    target = response.field_cells[0]
    forged_cell = _reseal_cell(target, **changes)
    cells = (forged_cell, *response.field_cells[1:])
    forged = _reseal_response(response, field_cells=cells)

    with pytest.raises(IndependentLiveValueDecoderError, match="reconstructed projection"):
        validate_decoded_live_response(forged)


def test_fully_resealed_inconsistent_presence_value_tuple_is_rejected() -> None:
    payload = _complete_payload("ScoreBoard")
    payload["futureScalar"] = 1
    response = _decode("ScoreBoard", payload)
    target = next(item for item in response.nodes if item.json_path == '$["futureScalar"]')
    forged_node = _reseal_node(
        target,
        presence_kind="null",
        value_sha256=live_decoder._canonical_sha256({"presence": "null", "value": 1}),
    )
    nodes = tuple(
        forged_node if item.node_ordinal == target.node_ordinal else item for item in response.nodes
    )
    forged = _reseal_response(
        response,
        nodes=nodes,
        null_node_count=response.null_node_count + 1,
    )

    with pytest.raises(IndependentLiveValueDecoderError, match="null-node algebra"):
        validate_decoded_live_response(forged)


def test_fully_resealed_zero_parser_length_is_rejected() -> None:
    response = _decode("Odds")
    forged = _reseal_response(response, parser_input_length=0)

    with pytest.raises(IndependentLiveValueDecoderError, match="must be positive"):
        validate_decoded_live_response(forged)


def test_contract_resource_digest_tampering_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_bytes = Path.read_bytes
    original = original_read_bytes(_RESOURCE)
    forged = original.replace(
        b'"live_contracts_sha256":"18750aec',
        b'"live_contracts_sha256":"08750aec',
        1,
    )
    assert forged != original

    def forged_read_bytes(path: Path) -> bytes:
        return forged if path == _RESOURCE else original_read_bytes(path)

    live_decoder._pinned_live_contracts.cache_clear()
    monkeypatch.setattr(Path, "read_bytes", forged_read_bytes)
    with pytest.raises(IndependentLiveValueDecoderError, match="differs from its exact pin"):
        pinned_live_decoder_contract_identities()
    monkeypatch.undo()
    live_decoder._pinned_live_contracts.cache_clear()
    assert len(pinned_live_decoder_contract_identities()) == 4


def test_module_imports_no_provider_parser_extract_or_orchestration_dependencies() -> None:
    source_path = Path(live_decoder.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    forbidden_prefixes = (
        "nba_api",
        "polars",
        "nbadb.extract",
        "nbadb.orchestrate",
    )
    assert not any(
        name == prefix or name.startswith(f"{prefix}.")
        for name in imported
        for prefix in forbidden_prefixes
    )

    script = f"""
import importlib.util
import sys
path = {str(source_path)!r}
name = 'isolated_independent_live_value_decoder'
spec = importlib.util.spec_from_file_location(name, path)
if spec is None or spec.loader is None:
    raise SystemExit('missing module spec')
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
forbidden = (
    'nba_api',
    'nbadb.extract.nba_api_adapter',
    'nbadb.extract.live_lossless',
    'nbadb.orchestrate',
)
loaded = tuple(name for name in sys.modules if any(
    name == prefix or name.startswith(prefix + '.') for prefix in forbidden
))
if loaded:
    raise SystemExit(repr(loaded))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
