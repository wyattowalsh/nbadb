from __future__ import annotations

import json

import pytest

import nbadb.contracts.independent_stats_projection_decoder as decoder
from nbadb.contracts.independent_stats_projection_decoder import (
    DecodedStatsProjectionResponseV1,
    IndependentStatsProjectionDecoderError,
    decode_stats_projection_response,
    pinned_stats_projection_decoder_contract_identities,
    replay_decoded_stats_projection_response,
    validate_decoded_stats_projection_response,
)

_UNKNOWN_ENDPOINT_IDS = (
    "VideoDetails",
    "VideoDetailsAsset",
    "VideoEvents",
    "VideoEventsAsset",
)


def _body(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode(
    endpoint_id: str,
    payload: object,
) -> tuple[bytes, DecodedStatsProjectionResponseV1]:
    contract = decoder._pinned_runtime_contracts()[endpoint_id]
    raw = _body(payload)
    response = decode_stats_projection_response(
        raw,
        endpoint_id=endpoint_id,
        endpoint_contract_sha256=contract.contract_sha256,
        provider_authority_sha256=pinned_stats_projection_decoder_contract_identities()[
            "provider_authority_sha256"
        ],
    )
    return raw, response


@pytest.mark.parametrize("endpoint_id", _UNKNOWN_ENDPOINT_IDS)
def test_exact_four_unknown_pins_admit_generic_nested_body_without_results(
    endpoint_id: str,
) -> None:
    payload = {
        "future": {
            "items": [1, None, {}, [], {"nested": True}],
            "label": "caf\u00e9",
        },
        "status": "ready",
    }
    raw, response = _decode(endpoint_id, payload)

    assert response.response_mode == "unknown_dynamic_response"
    assert response.provider_result_set_count == 0
    assert response.expected_result_set_count == 0
    assert response.result_count == 0
    assert response.results == ()
    assert json.loads(response.anomaly_codes_json) == ["unknown_dynamic_response"]
    assert [node.node_ordinal for node in response.residual_nodes] == list(
        range(response.residual_node_count)
    )
    by_path = {node.json_path: node for node in response.residual_nodes}
    assert by_path['$["future"]'].canonical_json is None
    assert by_path['$["future"]["items"][0]'].canonical_json == "1"
    assert by_path['$["future"]["items"][1]'].canonical_json == "null"
    assert by_path['$["future"]["items"][2]'].canonical_json == "{}"
    assert by_path['$["future"]["items"][3]'].canonical_json == "[]"
    assert by_path['$["future"]["items"][4]["nested"]'].canonical_json == "true"
    assert by_path['$["status"]'].canonical_json == '"ready"'
    assert response.residual_record_count == response.residual_node_count + 1
    assert (
        validate_decoded_stats_projection_response(
            response,
            parser_input_bytes=raw,
        )
        == response
    )
    assert (
        replay_decoded_stats_projection_response(
            response.canonical_bytes(),
            parser_input_bytes=raw,
            expected_response_sha256=response.response_sha256,
            expected_endpoint_contract_sha256=response.endpoint_contract_sha256,
            expected_provider_authority_sha256=response.provider_authority_sha256,
        )
        == response
    )


def test_scalar_key_body_has_zero_results_and_exact_residual_values() -> None:
    payload = {
        "status": "ready",
        "count": 2,
        "ratio": 0.5,
        "enabled": True,
        "nothing": None,
    }
    raw, response = _decode("VideoEvents", payload)
    repeated = decode_stats_projection_response(
        raw,
        endpoint_id=response.endpoint_id,
        endpoint_contract_sha256=response.endpoint_contract_sha256,
        provider_authority_sha256=response.provider_authority_sha256,
    )

    assert repeated == response
    assert response.results == ()
    assert response.provider_result_set_count == 0
    values = {
        node.object_key: (node.value_kind, node.canonical_json)
        for node in response.residual_nodes
        if node.parent_node_ordinal == 0
    }
    assert values == {
        "status": ("string", '"ready"'),
        "count": ("integer", "2"),
        "ratio": ("number", "0.5"),
        "enabled": ("boolean", "true"),
        "nothing": ("null", "null"),
    }


def test_empty_unknown_body_is_one_materialized_residual_root() -> None:
    _raw, response = _decode("VideoDetails", {})

    assert response.results == ()
    assert response.provider_result_set_count == 0
    assert response.residual_node_count == 1
    root = response.residual_nodes[0]
    assert (root.json_path, root.presence_kind, root.value_kind, root.canonical_json) == (
        "$",
        "empty_object",
        "object",
        "{}",
    )


def test_unknown_legacy_occurrence_semantics_remain_strict_and_residual_is_complete() -> None:
    payload = {
        "resultSets": [
            {"name": "Observed", "headers": [], "rowSet": [[]]},
            {
                "name": "Observed",
                "headers": ["A", "B"],
                "rowSet": [[1, {"nested": [True, None]}]],
            },
        ],
        "future": {"nested": [True, None]},
    }
    _raw, response = _decode("VideoEvents", payload)

    assert [result.result_name for result in response.results] == ["Observed", "Observed"]
    assert [result.provider_result_ordinal for result in response.results] == [0, 1]
    assert [result.result_duplicate_ordinal for result in response.results] == [0, 1]
    assert [result.raw_row_occurrence_count for result in response.results] == [1, 1]
    assert [result.canonical_result_ordinal for result in response.results] == [None, None]
    assert any(node.json_path == '$["future"]["nested"][1]' for node in response.residual_nodes)


def test_unknown_mode_rejects_ambiguous_or_malformed_legacy_envelopes() -> None:
    for payload in (
        {"resultSets": [], "resultSet": []},
        {"resultSets": "not-an-envelope"},
        {"resultSet": [{"name": "Observed", "headers": ["A"], "rowSet": [[]]}]},
    ):
        with pytest.raises(IndependentStatsProjectionDecoderError):
            _decode("VideoEvents", payload)


def test_duplicate_generic_object_keys_are_rejected_before_projection() -> None:
    contract = decoder._pinned_runtime_contracts()["VideoEvents"]
    with pytest.raises(IndependentStatsProjectionDecoderError, match="duplicate"):
        decode_stats_projection_response(
            b'{"future":{"value":1,"value":2}}',
            endpoint_id="VideoEvents",
            endpoint_contract_sha256=contract.contract_sha256,
            provider_authority_sha256=pinned_stats_projection_decoder_contract_identities()[
                "provider_authority_sha256"
            ],
        )


def test_unknown_generic_error_envelope_is_still_rejected() -> None:
    with pytest.raises(IndependentStatsProjectionDecoderError, match="error envelope"):
        _decode("VideoEvents", {"message": "provider failed", "details": {"retry": True}})


def test_generic_body_still_obeys_node_container_and_string_bounds(monkeypatch) -> None:
    with monkeypatch.context() as bounded:
        bounded.setattr(decoder, "MAX_JSON_NODES", 4)
        with pytest.raises(IndependentStatsProjectionDecoderError, match="node"):
            _decode("VideoEvents", {"future": {"items": [1, 2, 3]}})

    with monkeypatch.context() as bounded:
        bounded.setattr(decoder, "MAX_JSON_CONTAINER_ITEMS", 2)
        with pytest.raises(IndependentStatsProjectionDecoderError, match="container"):
            _decode("VideoEvents", {"first": 1, "second": 2, "third": 3})

    with monkeypatch.context() as bounded:
        bounded.setattr(decoder, "MAX_JSON_STRING_BYTES", 3)
        with pytest.raises(IndependentStatsProjectionDecoderError, match="byte bound"):
            _decode("VideoEvents", {"future": "value"})


def test_non_unknown_contract_still_rejects_nonlegacy_generic_body() -> None:
    contract = decoder._pinned_runtime_contracts()["CommonTeamYears"]
    with pytest.raises(IndependentStatsProjectionDecoderError, match="legacy"):
        decode_stats_projection_response(
            _body({"future": {"items": [1]}}),
            endpoint_id="CommonTeamYears",
            endpoint_contract_sha256=contract.contract_sha256,
            provider_authority_sha256=pinned_stats_projection_decoder_contract_identities()[
                "provider_authority_sha256"
            ],
        )
