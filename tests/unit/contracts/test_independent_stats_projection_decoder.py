from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import sys
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import nbadb.contracts.independent_stats_projection_decoder as decoder
from nbadb.contracts.independent_stats_projection_decoder import (
    CUSTOM_NESTED_ENDPOINT_IDS,
    DecodedStatsProjectionResponseV1,
    IndependentStatsProjectionDecoderError,
    decode_stats_projection_response,
    pinned_stats_projection_decoder_contract_identities,
    replay_decoded_stats_projection_response,
    validate_decoded_stats_projection_response,
)
from nbadb.contracts.independent_stats_value_decoder import (
    decode_stats_value_rows as decode_reference_rows,
)

if TYPE_CHECKING:
    from types import ModuleType


def _provider_pin() -> str:
    return pinned_stats_projection_decoder_contract_identities()["provider_authority_sha256"]


def _contract(endpoint_id: str):
    return decoder._pinned_runtime_contracts()[endpoint_id]


def _body(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()


def _decode(endpoint_id: str, payload: object) -> DecodedStatsProjectionResponseV1:
    contract = _contract(endpoint_id)
    return decode_stats_projection_response(
        _body(payload),
        endpoint_id=endpoint_id,
        endpoint_contract_sha256=contract.contract_sha256,
        provider_authority_sha256=_provider_pin(),
    )


def _legacy_payload(endpoint_id: str) -> dict[str, object]:
    contract = _contract(endpoint_id)
    return {
        "resultSets": [
            {
                "name": route.result_set_name,
                "headers": list(route.expected_columns),
                "rowSet": [],
            }
            for route in contract.result_sets
        ]
    }


@pytest.fixture(scope="module")
def reference_fixtures() -> ModuleType:
    path = Path(__file__).with_name("test_independent_stats_value_decoder.py")
    spec = importlib.util.spec_from_file_location("_stats_projection_reference_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _reseal_response_row(row: dict[str, object]) -> None:
    identity = {key: value for key, value in row.items() if key != "response_sha256"}
    row["response_sha256"] = decoder._projection_sha256(identity)


def _reseal_result_row(row: dict[str, object]) -> None:
    identity = {key: value for key, value in row.items() if key != "result_sha256"}
    row["result_sha256"] = decoder._projection_sha256(identity)


def _reseal_residual_roots(row: dict[str, object]) -> None:
    nodes = row["residual_nodes"]
    assert isinstance(nodes, list)
    node_digests = tuple(item["node_sha256"] for item in nodes)
    row["residual_node_root_sha256"] = decoder._ordered_projection_root(
        "decoded_stats_projection_residual_nodes_v1",
        node_digests,
    )
    row["residual_record_root_sha256"] = decoder._ordered_projection_root(
        "decoded_stats_projection_residual_records_v1",
        (row["canonical_payload_sha256"], *node_digests),
    )
    _reseal_response_row(row)


def test_frozen_contract_and_provider_census_is_exact() -> None:
    identities = dict(pinned_stats_projection_decoder_contract_identities())
    contracts = decoder._pinned_runtime_contracts()
    custom = {
        endpoint_id
        for endpoint_id, contract in contracts.items()
        if contract.parser_kind == "custom_nested"
    }

    assert identities == {
        "decoder_contract_sha256": (
            "3e2b2e9b5c9d42644e59f4382e286465208bea9639270517a4bb40ccde5d169d"
        ),
        "provider_authority_sha256": (
            "e5981c0223c99ecd4a483606781d1433cc23f22b26ec71c41a3b12b9ad827085"
        ),
        "runtime_contract_payload_sha256": (
            "7c9b59c475cff6b0b9d3619bdfe9a3849e11619980f6d15a1cafd5f269f61b3b"
        ),
        "runtime_contract_resource_sha256": (
            "24ed29f72f19de9e9c02ed4e4f8363b0e2b0809ce59886975f2f739cc80665b4"
        ),
        "stats_contracts_sha256": (
            "a9838c5464d5410210fc3d5af3d3f75c1a796eb46ff999079749a1a4b77f4309"
        ),
    }
    assert len(contracts) == 139
    assert len(contracts) - len(custom) == 122
    assert custom == CUSTOM_NESTED_ENDPOINT_IDS
    assert sum(len(contracts[item].result_sets) for item in custom) == 44


def test_all_139_frozen_contracts_decode_and_replay(reference_fixtures: ModuleType) -> None:
    contracts = decoder._pinned_runtime_contracts()
    for endpoint_id, contract in contracts.items():
        payload = (
            reference_fixtures._payload_for(endpoint_id)
            if contract.parser_kind == "custom_nested"
            else _legacy_payload(endpoint_id)
        )
        raw = _body(payload)
        response = decode_stats_projection_response(
            raw,
            endpoint_id=endpoint_id,
            endpoint_contract_sha256=contract.contract_sha256,
            provider_authority_sha256=_provider_pin(),
        )
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
                expected_endpoint_contract_sha256=contract.contract_sha256,
                expected_provider_authority_sha256=_provider_pin(),
            )
            == response
        )


@pytest.mark.parametrize("endpoint_id", sorted(CUSTOM_NESTED_ENDPOINT_IDS))
def test_custom_projection_matches_independent_reference_decoder(
    endpoint_id: str,
    reference_fixtures: ModuleType,
) -> None:
    payload = reference_fixtures._payload_for(endpoint_id)
    raw = _body(payload)
    contract = _contract(endpoint_id)
    projected = _decode(endpoint_id, payload)
    reference = decode_reference_rows(
        endpoint_id=endpoint_id,
        endpoint_contract_sha256=contract.contract_sha256,
        provider_authority_sha256=_provider_pin(),
        parser_input=raw,
    )

    assert projected.provider_result_set_count == len(reference)
    assert projected.expected_result_set_count == len(reference)
    assert tuple(item.result_name for item in projected.results) == tuple(
        item.result_name for item in reference
    )
    for projected_result, reference_result in zip(projected.results, reference, strict=True):
        raw_headers = json.loads(projected_result.raw_headers_json)
        raw_rows = json.loads(projected_result.raw_rows_json)
        anomalies = json.loads(projected_result.anomaly_codes_json)
        assert tuple(raw_headers) == reference_result.ordered_headers
        assert tuple(tuple(row) for row in raw_rows) == reference_result.rows
        assert (
            decoder._normalized_output_sha256(raw_headers, raw_rows)
            == reference_result.normalized_output_sha256
        )
        assert projected_result.normalized_output_sha256 == decoder._observed_output_sha256(
            raw_headers=raw_headers,
            raw_rows=raw_rows,
            anomaly_codes=anomalies,
        )


def test_duplicate_additive_and_missing_results_remain_distinct() -> None:
    headers = list(_contract("CommonTeamYears").result_sets[0].expected_columns)
    duplicate = _decode(
        "CommonTeamYears",
        {
            "resultSets": [
                {"name": "TeamYears", "headers": headers, "rowSet": []},
                {"name": "TeamYears", "headers": headers, "rowSet": []},
                {"name": "Extra", "headers": ["X"], "rowSet": [[1]]},
            ]
        },
    )
    missing = _decode(
        "CommonTeamYears",
        {"resultSets": [{"name": "Extra", "headers": ["X"], "rowSet": []}]},
    )

    assert json.loads(duplicate.anomaly_codes_json) == [
        "additive_result_set",
        "duplicate_result_set_name",
    ]
    assert [item.result_duplicate_ordinal for item in duplicate.results] == [0, 1, 0]
    assert [item.presence for item in missing.results] == ["present_empty", "missing"]
    assert json.loads(missing.anomaly_codes_json) == [
        "additive_result_set",
        "missing_result_set",
    ]


def test_header_slots_preserve_non_string_duplicates_and_ragged_cells() -> None:
    response = _decode(
        "CommonTeamYears",
        {
            "resultSets": [
                {
                    "name": "TeamYears",
                    "headers": ["LEAGUE_ID", 7, "LEAGUE_ID"],
                    "rowSet": [["00", 1, 2, 3], "not-a-row", [None]],
                }
            ]
        },
    )
    result = response.results[0]
    slots = json.loads(result.ordered_header_slots_json)
    cells = [record for record in result.records if record.record_kind == "cell"]

    assert [slot["header_reference_kind"] for slot in slots] == [
        "named",
        "non_string",
        "named",
        "out_of_range",
    ]
    assert result.raw_row_occurrence_count == 3
    assert result.sequence_row_count == 2
    assert result.cell_count == 5
    out_of_range = next(item for item in cells if item.header_reference_kind == "out_of_range")
    assert out_of_range.header_value_sha256 is None
    assert set(json.loads(result.anomaly_codes_json)) >= {
        "duplicate_header",
        "non_sequence_row",
        "ragged_row",
        "unsupported_header_shape",
    }


def test_whole_response_residual_is_iterative_preorder_and_materializes_only_leaves() -> None:
    payload = _legacy_payload("CommonTeamYears")
    payload["meta"] = {"items": [1, None, {}, []], "unicode": "caf\u00e9"}
    response = _decode("CommonTeamYears", payload)
    nodes = response.residual_nodes
    by_path = {node.json_path: node for node in nodes}

    assert nodes[0].json_path == "$"
    assert [node.node_ordinal for node in nodes] == list(range(len(nodes)))
    assert by_path['$["meta"]["items"]'].canonical_json is None
    assert by_path['$["meta"]["items"][0]'].canonical_json == "1"
    assert by_path['$["meta"]["items"][1]'].canonical_json == "null"
    assert by_path['$["meta"]["items"][2]'].canonical_json == "{}"
    assert by_path['$["meta"]["items"][3]'].canonical_json == "[]"
    assert response.residual_record_count == response.residual_node_count + 1


def test_unicode_null_empty_mixed_values_keep_exact_canonical_records() -> None:
    response = _decode(
        "CommonTeamYears",
        {
            "resultSets": [
                {
                    "name": "TeamYears",
                    "headers": ["A", "B", "C", "D", "E", "F", "G"],
                    "rowSet": [[None, True, -0.0, "\u2603", {}, [], 9_007_199_254_740_991]],
                }
            ]
        },
    )
    cells = [record for record in response.results[0].records if record.record_kind == "cell"]

    assert [item.value_kind for item in cells] == [
        "null",
        "boolean",
        "number",
        "string",
        "object",
        "array",
        "integer",
    ]
    assert [item.presence_kind for item in cells][4:6] == ["empty_object", "empty_array"]
    assert cells[3].canonical_json == '"\u2603"'


@pytest.mark.parametrize(
    "raw",
    [
        b'{"resultSets":[],"resultSets":[]}',
        b'{"meta":' + (b"[" * 65) + b"0" + (b"]" * 65) + b',"resultSets":[]}',
        b'{"meta":' + (b"1" * 65) + b',"resultSets":[]}',
        b'{"meta":1e999,"resultSets":[]}',
    ],
)
def test_lexical_depth_duplicate_key_and_number_guards_run_before_admission(raw: bytes) -> None:
    contract = _contract("CommonTeamYears")
    with pytest.raises(IndependentStatsProjectionDecoderError):
        decode_stats_projection_response(
            raw,
            endpoint_id="CommonTeamYears",
            endpoint_contract_sha256=contract.contract_sha256,
            provider_authority_sha256=_provider_pin(),
        )


def test_depth_preflight_rejects_before_json_loads(monkeypatch) -> None:
    contract = _contract("CommonTeamYears")
    deep = b'{"meta":' + (b"[" * 65) + b"0" + (b"]" * 65) + b',"resultSets":[]}'

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("json.loads ran before the lexical depth gate")

    monkeypatch.setattr(decoder.json, "loads", _must_not_run)
    with pytest.raises(IndependentStatsProjectionDecoderError, match="depth"):
        decode_stats_projection_response(
            deep,
            endpoint_id="CommonTeamYears",
            endpoint_contract_sha256=contract.contract_sha256,
            provider_authority_sha256=_provider_pin(),
        )


def test_parser_byte_node_and_string_bounds_fail_without_large_allocations(monkeypatch) -> None:
    contract = _contract("CommonTeamYears")
    raw = _body(_legacy_payload("CommonTeamYears"))
    with monkeypatch.context() as bounded:
        bounded.setattr(decoder, "MAX_PARSER_INPUT_BYTES", len(raw) - 1)
        with pytest.raises(IndependentStatsProjectionDecoderError, match="exceed"):
            decode_stats_projection_response(
                raw,
                endpoint_id="CommonTeamYears",
                endpoint_contract_sha256=contract.contract_sha256,
                provider_authority_sha256=_provider_pin(),
            )
    with monkeypatch.context() as bounded:
        bounded.setattr(decoder, "MAX_JSON_NODES", 3)
        with pytest.raises(IndependentStatsProjectionDecoderError, match="node"):
            _decode("CommonTeamYears", _legacy_payload("CommonTeamYears"))
    with monkeypatch.context() as bounded:
        bounded.setattr(decoder, "MAX_JSON_STRING_BYTES", 3)
        with pytest.raises(IndependentStatsProjectionDecoderError, match="byte bound"):
            _decode("CommonTeamYears", _legacy_payload("CommonTeamYears"))


def test_recursion_error_and_secret_bearing_errors_are_normalized(monkeypatch) -> None:
    _contract("CommonTeamYears")

    def _raise_recursion(*_args, **_kwargs):
        raise RecursionError("Authorization: Bearer do-not-leak")

    monkeypatch.setattr(decoder.json, "loads", _raise_recursion)
    with pytest.raises(IndependentStatsProjectionDecoderError) as error:
        _decode("CommonTeamYears", _legacy_payload("CommonTeamYears"))
    assert "do-not-leak" not in str(error.value)
    assert "Authorization" not in str(error.value)
    assert error.value.__cause__ is None


def test_error_envelope_never_reflects_provider_secret_text() -> None:
    contract = _contract("CommonTeamYears")
    with pytest.raises(IndependentStatsProjectionDecoderError) as error:
        decode_stats_projection_response(
            _body({"statusCode": 401, "message": "Basic top-secret"}),
            endpoint_id="CommonTeamYears",
            endpoint_contract_sha256=contract.contract_sha256,
            provider_authority_sha256=_provider_pin(),
        )
    assert "top-secret" not in str(error.value)


def test_exact_dto_type_and_external_replay_pins_are_fail_closed() -> None:
    raw = _body(_legacy_payload("CommonTeamYears"))
    response = decode_stats_projection_response(
        raw,
        endpoint_id="CommonTeamYears",
        endpoint_contract_sha256=_contract("CommonTeamYears").contract_sha256,
        provider_authority_sha256=_provider_pin(),
    )

    class ForeignProjectionResponse(DecodedStatsProjectionResponseV1):
        pass

    values = {field.name: getattr(response, field.name) for field in fields(response)}
    foreign = ForeignProjectionResponse(**values)
    with pytest.raises(IndependentStatsProjectionDecoderError):
        validate_decoded_stats_projection_response(foreign, parser_input_bytes=raw)
    with pytest.raises(IndependentStatsProjectionDecoderError):
        replay_decoded_stats_projection_response(
            response.canonical_bytes(),
            parser_input_bytes=raw,
            expected_response_sha256="0" * 64,
            expected_endpoint_contract_sha256=response.endpoint_contract_sha256,
            expected_provider_authority_sha256=response.provider_authority_sha256,
        )


def test_validation_and_replay_require_exact_source_bytes_and_independent_redecode() -> None:
    payload = _legacy_payload("CommonTeamYears")
    raw = _body(payload)
    response = decode_stats_projection_response(
        raw,
        endpoint_id="CommonTeamYears",
        endpoint_contract_sha256=_contract("CommonTeamYears").contract_sha256,
        provider_authority_sha256=_provider_pin(),
    )

    detached_row = response.to_row()
    detached_row["parser_input_sha256"] = "0" * 64
    detached_row["parser_input_length"] = len(raw) + 1
    _reseal_response_row(detached_row)
    detached = DecodedStatsProjectionResponseV1.from_row(detached_row)
    with pytest.raises(IndependentStatsProjectionDecoderError, match="parser-input bytes"):
        validate_decoded_stats_projection_response(detached, parser_input_bytes=raw)
    with pytest.raises(IndependentStatsProjectionDecoderError, match="parser-input bytes"):
        replay_decoded_stats_projection_response(
            detached.canonical_bytes(),
            parser_input_bytes=raw,
            expected_response_sha256=detached.response_sha256,
            expected_endpoint_contract_sha256=detached.endpoint_contract_sha256,
            expected_provider_authority_sha256=detached.provider_authority_sha256,
        )

    other_payload = copy.deepcopy(payload)
    other_payload["metadata"] = {"independent": True}
    other_raw = _body(other_payload)
    semantic_row = response.to_row()
    semantic_row["parser_input_sha256"] = hashlib.sha256(other_raw).hexdigest()
    semantic_row["parser_input_length"] = len(other_raw)
    _reseal_response_row(semantic_row)
    semantic_forgery = DecodedStatsProjectionResponseV1.from_row(semantic_row)
    with pytest.raises(IndependentStatsProjectionDecoderError, match="independent parser-input"):
        validate_decoded_stats_projection_response(
            semantic_forgery,
            parser_input_bytes=other_raw,
        )

    class ForeignBytes(bytes):
        pass

    with pytest.raises(IndependentStatsProjectionDecoderError, match="parser-input bytes"):
        validate_decoded_stats_projection_response(
            response,
            parser_input_bytes=ForeignBytes(raw),
        )


def test_projection_rows_require_exact_discriminators_and_scalar_types() -> None:
    payload = _legacy_payload("CommonTeamYears")
    payload["metadata"] = {"child": 1}
    response = _decode("CommonTeamYears", payload)
    result = response.results[0]
    record = next(item for item in result.records if item.record_kind == "header")
    object_node = next(
        item for item in response.residual_nodes if item.json_path == '$["metadata"]'
    )
    leaf_node = next(
        item for item in response.residual_nodes if item.json_path == '$["metadata"]["child"]'
    )

    rows_and_types = (
        (record.to_row(), decoder.DecodedStatsProjectionRecordV1),
        (result.to_row(), decoder.DecodedStatsProjectionResultV1),
        (object_node.to_row(), decoder.DecodedStatsResidualNodeV1),
        (response.to_row(), DecodedStatsProjectionResponseV1),
    )
    for source_row, cls in rows_and_types:
        for field_name, replacement in (
            ("schema_version", True),
            ("kind", "foreign_projection_kind"),
        ):
            row = copy.deepcopy(source_row)
            row[field_name] = replacement
            with pytest.raises(IndependentStatsProjectionDecoderError):
                cls.from_row(row)

    class ForeignString(str):
        pass

    for dto, cls in (
        (record, decoder.DecodedStatsProjectionRecordV1),
        (result, decoder.DecodedStatsProjectionResultV1),
        (object_node, decoder.DecodedStatsResidualNodeV1),
        (leaf_node, decoder.DecodedStatsResidualNodeV1),
        (response, DecodedStatsProjectionResponseV1),
    ):
        for dto_field in fields(dto):
            current = getattr(dto, dto_field.name)
            if type(current) is not str:
                continue
            row = dto.to_row()
            row[dto_field.name] = ForeignString(current)
            with pytest.raises(IndependentStatsProjectionDecoderError):
                cls.from_row(row)

    for ordinal_name in (
        "provider_result_ordinal",
        "expected_result_ordinal",
        "canonical_result_ordinal",
    ):
        row = result.to_row()
        assert row[ordinal_name] == 0
        row[ordinal_name] = False
        _reseal_result_row(row)
        with pytest.raises(IndependentStatsProjectionDecoderError, match="ordinal"):
            decoder.DecodedStatsProjectionResultV1.from_row(row)

    node_row = leaf_node.to_row()
    assert node_row["object_key_ordinal"] == 0
    node_row["object_key_ordinal"] = False
    node_row["node_sha256"] = decoder._projection_sha256(
        {key: value for key, value in node_row.items() if key != "node_sha256"}
    )
    with pytest.raises(IndependentStatsProjectionDecoderError, match="object-key ordinal"):
        decoder.DecodedStatsResidualNodeV1.from_row(node_row)


def test_coordinated_result_reseal_cannot_escape_residual_reconstruction() -> None:
    payload_a = _legacy_payload("CommonTeamYears")
    payload_b = copy.deepcopy(payload_a)
    result_b = payload_b["resultSets"][0]
    assert isinstance(result_b, dict)
    result_b["rowSet"] = [[None] * len(result_b["headers"])]
    response_a = _decode("CommonTeamYears", payload_a)
    response_b = _decode("CommonTeamYears", payload_b)
    row = response_a.to_row()
    row["results"] = [item.to_row() for item in response_b.results]
    row["result_root_sha256"] = response_b.result_root_sha256
    _reseal_response_row(row)

    with pytest.raises(
        IndependentStatsProjectionDecoderError,
        match="differ from the residual response",
    ):
        DecodedStatsProjectionResponseV1.from_row(row)


@pytest.mark.parametrize(
    ("field", "replacement", "pattern"),
    [
        ("json_path", '$["meta"]["wrong"]', "child path"),
        ("parent_json_path", '$["wrong"]', "parent path"),
        ("depth", 1, "parent path or depth"),
        ("object_key_ordinal", 7, "sibling order"),
    ],
)
def test_coordinated_residual_reseal_rejects_tree_coordinate_drift(
    field: str,
    replacement: object,
    pattern: str,
) -> None:
    payload = _legacy_payload("CommonTeamYears")
    payload["meta"] = {"value": 1}
    response = _decode("CommonTeamYears", payload)
    row = response.to_row()
    nodes = row["residual_nodes"]
    assert isinstance(nodes, list)
    target = next(item for item in nodes if item["json_path"] == '$["meta"]["value"]')
    target[field] = replacement
    node_identity = {key: value for key, value in target.items() if key != "node_sha256"}
    target["node_sha256"] = decoder._projection_sha256(node_identity)
    node_digests = tuple(item["node_sha256"] for item in nodes)
    row["residual_node_root_sha256"] = decoder._ordered_projection_root(
        "decoded_stats_projection_residual_nodes_v1", node_digests
    )
    row["residual_record_root_sha256"] = decoder._ordered_projection_root(
        "decoded_stats_projection_residual_records_v1",
        (row["canonical_payload_sha256"], *node_digests),
    )
    _reseal_response_row(row)

    with pytest.raises(IndependentStatsProjectionDecoderError, match=pattern):
        DecodedStatsProjectionResponseV1.from_row(row)


def test_fully_resealed_interleaved_residual_subtrees_are_not_canonical_preorder() -> None:
    payload = {
        "left": {"leaf": 1},
        "right": {"leaf": 2},
        **_legacy_payload("CommonTeamYears"),
    }
    response = _decode("CommonTeamYears", payload)
    row = response.to_row()
    nodes = row["residual_nodes"]
    assert isinstance(nodes, list)
    by_path = {item["json_path"]: item for item in nodes}
    priority = (
        "$",
        '$["left"]',
        '$["right"]',
        '$["left"]["leaf"]',
        '$["right"]["leaf"]',
    )
    selected = set(priority)
    reordered = [by_path[path] for path in priority]
    reordered.extend(item for item in nodes if item["json_path"] not in selected)
    old_to_new = {item["node_ordinal"]: new_ordinal for new_ordinal, item in enumerate(reordered)}
    for new_ordinal, item in enumerate(reordered):
        old_parent = item["parent_node_ordinal"]
        item["node_ordinal"] = new_ordinal
        item["parent_node_ordinal"] = None if old_parent is None else old_to_new[old_parent]
        item["node_sha256"] = decoder._projection_sha256(
            {key: value for key, value in item.items() if key != "node_sha256"}
        )
    row["residual_nodes"] = reordered
    _reseal_residual_roots(row)

    with pytest.raises(IndependentStatsProjectionDecoderError, match="canonical preorder"):
        DecodedStatsProjectionResponseV1.from_row(row)


def test_canonical_replay_rejects_pretty_reordered_and_duplicate_key_bytes() -> None:
    raw = _body(_legacy_payload("CommonTeamYears"))
    response = decode_stats_projection_response(
        raw,
        endpoint_id="CommonTeamYears",
        endpoint_contract_sha256=_contract("CommonTeamYears").contract_sha256,
        provider_authority_sha256=_provider_pin(),
    )
    row = response.to_row()
    pretty = json.dumps(row, indent=2, ensure_ascii=False).encode()
    duplicate = response.canonical_bytes()[:-1] + b',"response_sha256":"' + (b"0" * 64) + b'"}'

    for encoded in (pretty, duplicate):
        with pytest.raises(IndependentStatsProjectionDecoderError):
            replay_decoded_stats_projection_response(
                encoded,
                parser_input_bytes=raw,
                expected_response_sha256=response.response_sha256,
                expected_endpoint_contract_sha256=response.endpoint_contract_sha256,
                expected_provider_authority_sha256=response.provider_authority_sha256,
            )


def test_foreign_contract_provider_and_resource_pins_fail_before_decode(monkeypatch) -> None:
    contract = _contract("CommonTeamYears")
    raw = _body(_legacy_payload("CommonTeamYears"))
    for endpoint_pin, provider_pin in (
        ("0" * 64, _provider_pin()),
        (contract.contract_sha256, "0" * 64),
    ):
        with pytest.raises(IndependentStatsProjectionDecoderError):
            decode_stats_projection_response(
                raw,
                endpoint_id="CommonTeamYears",
                endpoint_contract_sha256=endpoint_pin,
                provider_authority_sha256=provider_pin,
            )

    decoder._pinned_runtime_contracts.cache_clear()
    monkeypatch.setattr(decoder.Path, "read_bytes", lambda _self: b"{}")
    with pytest.raises(IndependentStatsProjectionDecoderError, match="resource digest"):
        decoder._pinned_runtime_contracts()
    decoder._pinned_runtime_contracts.cache_clear()


def test_source_is_stdlib_only_and_residual_builder_has_no_recursive_call() -> None:
    source_path = Path(decoder.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    banned_roots = {"polars", "pandera", "duckdb", "nbadb"}
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(item.name.split(".", 1)[0] for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots.isdisjoint(banned_roots)
    assert "independent_stats_value_decoder" not in source_path.read_text(encoding="utf-8")

    residual_builder = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_residual_nodes"
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_build_residual_nodes"
        for node in ast.walk(residual_builder)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
        and node.func.attr == "dumps"
        for node in ast.walk(residual_builder)
    )


def test_projection_digest_changes_when_any_material_partition_changes() -> None:
    payload = _legacy_payload("CommonTeamYears")
    base = _decode("CommonTeamYears", payload)
    changed_payload = copy.deepcopy(payload)
    changed_payload["metadata"] = {"fixed": 0}
    changed = _decode("CommonTeamYears", changed_payload)

    assert base.result_root_sha256 == changed.result_root_sha256
    assert base.residual_node_root_sha256 != changed.residual_node_root_sha256
    assert base.canonical_payload_sha256 != changed.canonical_payload_sha256
    assert base.response_sha256 != changed.response_sha256
    assert (
        hashlib.sha256(base.canonical_bytes()).hexdigest()
        != hashlib.sha256(changed.canonical_bytes()).hexdigest()
    )
