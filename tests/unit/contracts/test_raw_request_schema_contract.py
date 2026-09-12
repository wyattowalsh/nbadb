from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest

from nbadb.contracts.raw_request_schema_contract import (
    RAW_REQUEST_SCHEMA_CONTRACT_KIND,
    RAW_REQUEST_SCHEMA_CONTRACT_SCHEMA_VERSION,
    RawRequestSchemaContractError,
    RawRequestSchemaContractV2,
    compile_raw_request_schema_contract,
    parse_raw_request_schema_contract,
)


def _rewrite(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _refresh_contract_digest(payload: dict[str, Any]) -> None:
    content = {key: value for key, value in payload.items() if key != "contract_sha256"}
    payload["contract_sha256"] = hashlib.sha256(_rewrite(content)).hexdigest()


def _refresh_table_digest(table: dict[str, Any]) -> None:
    content = {key: value for key, value in table.items() if key != "schema_sha256"}
    table["schema_sha256"] = hashlib.sha256(_rewrite(content)).hexdigest()


def _refresh_nested_contract_digests(payload: dict[str, Any]) -> None:
    bundle_json = payload["bundle_json_schema_json"]
    tables = payload["tables"]
    assert isinstance(bundle_json, str) and isinstance(tables, list)
    payload["bundle_json_schema_sha256"] = hashlib.sha256(bundle_json.encode()).hexdigest()
    payload["table_inventory_sha256"] = hashlib.sha256(_rewrite(tables)).hexdigest()
    _refresh_contract_digest(payload)


@pytest.fixture(scope="module")
def contract() -> RawRequestSchemaContractV2:
    return compile_raw_request_schema_contract()


def test_compiles_exact_four_table_v2_public_schema(
    contract: RawRequestSchemaContractV2,
) -> None:
    assert contract.schema_version == RAW_REQUEST_SCHEMA_CONTRACT_SCHEMA_VERSION == 2
    assert contract.kind == RAW_REQUEST_SCHEMA_CONTRACT_KIND
    assert contract.authority_schema_version == 2
    assert [table.table_name for table in contract.tables] == [
        "raw_nba_api_observation_route_landing",
        "raw_nba_api_parser_input_object",
        "raw_nba_api_request_observation",
        "raw_nba_api_result_occurrence",
    ]
    assert [table.primary_key for table in contract.tables] == [
        "landing_sha256",
        "object_sha256",
        "observation_sha256",
        "occurrence_sha256",
    ]
    assert [len(table.columns) for table in contract.tables] == [30, 12, 53, 29]
    assert sum(len(table.columns) for table in contract.tables) == 124
    assert all(
        (table.strict, table.coerce, table.ordered) == (True, False, True)
        for table in contract.tables
    )


def test_contract_binds_only_v2_runtime_bundle_and_convenience_codec(
    contract: RawRequestSchemaContractV2,
) -> None:
    bundle_schema = json.loads(contract.bundle_json_schema_json)
    assert contract.convenience_scalar_codec_schema_version == 1
    assert contract.convenience_scalar_codec_tag == "nbadb.raw.scalar"
    assert contract.public_parser_input_representation == (
        "nbadb_public_exact_decoded_response_text_utf8_v1"
    )
    assert contract.parser_input_codec == "gzip-6-public-v1"
    assert contract.max_parser_input_bytes > 0
    assert contract.max_parser_input_stored_bytes > contract.max_parser_input_bytes
    assert contract.max_authority_rows > 0
    assert bundle_schema["additionalProperties"] is False
    assert {
        "ParserInputObjectV2",
        "RequestAttemptIdentityV2",
        "RequestObservationV2",
        "ResultOccurrenceV2",
        "ObservationRouteLandingV2",
    } <= set(bundle_schema["$defs"])
    assert {
        "ParserInputObjectV1",
        "RequestAttemptIdentityV1",
        "RequestObservationV1",
        "ResultOccurrenceV1",
    }.isdisjoint(bundle_schema["$defs"])
    assert bundle_schema["title"] == "RawRequestAuthorityBundleV2"


def test_columns_preserve_order_checks_and_landing_semantics(
    contract: RawRequestSchemaContractV2,
) -> None:
    tables = {table.table_name: table for table in contract.tables}
    parser = tables["raw_nba_api_parser_input_object"]
    observation = tables["raw_nba_api_request_observation"]
    occurrence = tables["raw_nba_api_result_occurrence"]
    landing = tables["raw_nba_api_observation_route_landing"]

    assert parser.columns[-1].name == "stored_payload"
    assert parser.columns[-1].logical_type == "binary"
    assert [
        column.name for column in observation.columns if column.logical_type == "datetime[us,UTC]"
    ] == ["started_at", "finished_at"]
    by_observation_column = {column.name: column for column in observation.columns}
    assert by_observation_column["route_landing_count"].ordinal == 46
    assert by_observation_column["route_landings_sha256"].ordinal == 47
    assert occurrence.dataframe_checks == (("parent_empty_unobserved_is_exact_live_state", "{}"),)
    assert landing.dataframe_checks == (("semantic_partition_is_exact", "{}"),)
    by_landing_column = {column.name: column for column in landing.columns}
    assert by_landing_column["landing_sha256"].unique is True
    assert by_landing_column["live_snapshot_at"].logical_type == "datetime[us,UTC]"
    assert by_landing_column["live_snapshot_at"].nullable is True
    assert "response_canonical_alias" in by_landing_column["landing_semantic"].checks[0][1]
    assert by_landing_column["committed_receipt_schema_version"].checks == (
        ("equal_to", '{"value":2}'),
    )


def test_compile_is_deterministic_and_canonical_roundtrip(
    contract: RawRequestSchemaContractV2,
) -> None:
    second = compile_raw_request_schema_contract()
    assert second == contract
    assert second.canonical_bytes == contract.canonical_bytes
    assert parse_raw_request_schema_contract(contract.canonical_bytes) == contract
    assert RawRequestSchemaContractV2.from_dict(contract.to_dict()) == contract


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("contract_sha256",), "0" * 64, "digest is stale"),
        (("bundle_json_schema_sha256",), "0" * 64, "digest is stale"),
        (("table_inventory_sha256",), "0" * 64, "digest is stale"),
        (("authority_schema_version",), 1, "version drifted"),
        (("schema_version",), 1, "identity is invalid"),
        (("tables", 0, "schema_sha256"), "0" * 64, "schema digest is stale"),
    ],
)
def test_rejects_v1_forged_or_stale_derived_authority(
    contract: RawRequestSchemaContractV2,
    path: tuple[object, ...],
    value: object,
    message: str,
) -> None:
    payload = contract.to_dict()
    target: Any = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(RawRequestSchemaContractError, match=message):
        parse_raw_request_schema_contract(_rewrite(payload))


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("authority_schema_version", True),
        ("authority_schema_version", 2.0),
        ("authority_schema_version", "2"),
        ("convenience_scalar_codec_schema_version", True),
        ("convenience_scalar_codec_schema_version", 1.0),
        ("convenience_scalar_codec_schema_version", "1"),
        ("max_parser_input_bytes", True),
        ("max_parser_input_bytes", 67_108_864.0),
        ("max_parser_input_stored_bytes", True),
        ("max_parser_input_stored_bytes", 67_174_400.0),
        ("max_authority_rows", True),
        ("max_authority_rows", 1_000_000.0),
    ],
)
def test_rejects_noninteger_versions_with_recomputed_digest(
    contract: RawRequestSchemaContractV2,
    field_name: str,
    invalid_value: object,
) -> None:
    payload = contract.to_dict()
    payload[field_name] = invalid_value
    _refresh_contract_digest(payload)
    with pytest.raises(
        RawRequestSchemaContractError,
        match=rf"{field_name} must be an exact integer",
    ):
        parse_raw_request_schema_contract(_rewrite(payload))


def test_rejects_self_resealed_foreign_runtime_and_pandera_schema(
    contract: RawRequestSchemaContractV2,
) -> None:
    payload = contract.to_dict()
    payload["bundle_json_schema_json"] = "{}"
    _refresh_nested_contract_digests(payload)
    with pytest.raises(
        RawRequestSchemaContractError,
        match="differs from current runtime authority",
    ):
        parse_raw_request_schema_contract(_rewrite(payload))

    payload = contract.to_dict()
    tables = payload["tables"]
    assert isinstance(tables, list) and isinstance(tables[0], dict)
    table = tables[0]
    table["description"] = f"{table['description']} foreign"
    _refresh_table_digest(table)
    _refresh_nested_contract_digests(payload)
    with pytest.raises(
        RawRequestSchemaContractError,
        match="differs from current Pandera authority",
    ):
        parse_raw_request_schema_contract(_rewrite(payload))


def test_rejects_extra_missing_duplicate_and_noncanonical_members(
    contract: RawRequestSchemaContractV2,
) -> None:
    payload = contract.to_dict()
    payload["extra"] = True
    with pytest.raises(RawRequestSchemaContractError, match="schema is not exact"):
        parse_raw_request_schema_contract(_rewrite(payload))

    payload = contract.to_dict()
    payload.pop("tables")
    with pytest.raises(RawRequestSchemaContractError, match="schema is not exact"):
        parse_raw_request_schema_contract(_rewrite(payload))

    duplicate = contract.canonical_bytes.replace(
        b'{"authority_schema_version":2,',
        b'{"authority_schema_version":2,"authority_schema_version":2,',
        1,
    )
    with pytest.raises(RawRequestSchemaContractError, match="duplicate key"):
        parse_raw_request_schema_contract(duplicate)

    with pytest.raises(RawRequestSchemaContractError, match="not canonical"):
        parse_raw_request_schema_contract(contract.canonical_bytes + b"\n")


def test_rejects_missing_fourth_table_foreign_table_and_noncontiguous_columns(
    contract: RawRequestSchemaContractV2,
) -> None:
    table = contract.tables[0]
    broken_column = replace(table.columns[0], ordinal=2)
    with pytest.raises(RawRequestSchemaContractError, match="ordinals are not contiguous"):
        replace(table, columns=(broken_column, *table.columns[1:]))

    with pytest.raises(RawRequestSchemaContractError, match="inventory is incomplete"):
        replace(contract, tables=contract.tables[1:])

    foreign = replace(contract.tables[0], table_name="raw_nba_api_foreign")
    with pytest.raises(RawRequestSchemaContractError, match="inventory is incomplete"):
        replace(contract, tables=tuple(sorted((foreign, *contract.tables[1:]))))
