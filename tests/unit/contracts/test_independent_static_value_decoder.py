from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
import sys
from collections import Counter
from dataclasses import FrozenInstanceError, replace
from functools import lru_cache
from importlib.metadata import distribution
from pathlib import Path
from typing import cast

import pytest

import nbadb.contracts.independent_static_value_decoder as static_decoder
from nbadb.contracts.independent_static_value_decoder import (
    DecodedStaticCellV1,
    DecodedStaticFieldV1,
    DecodedStaticRecordV1,
    DecodedStaticResponseV1,
    IndependentStaticValueDecoderError,
    decode_static_value_response,
    decode_static_value_rows,
    pinned_static_decoder_contract_identities,
    validate_decoded_static_response,
)

_RESOURCE = (
    Path(__file__).parents[3]
    / "src"
    / "nbadb"
    / "contracts"
    / "nba_api_runtime_contract_v1_11_4.json"
)
_DATASET_SYMBOLS = {
    "static_players": "players",
    "static_teams": "teams",
    "static_wnba_players": "wnba_players",
    "static_wnba_teams": "wnba_teams",
}


def _raw_contracts() -> dict[str, dict[str, object]]:
    payload = json.loads(_RESOURCE.read_bytes())
    return cast("dict[str, dict[str, object]]", payload["static_contracts"])


@lru_cache(maxsize=1)
def _source_rows_by_dataset() -> dict[str, list[list[object]]]:
    source_path = distribution("nba_api").locate_file("nba_api/stats/library/data.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    by_symbol: dict[str, list[list[object]]] = {}
    wanted = set(_DATASET_SYMBOLS.values())
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in wanted:
            value = ast.literal_eval(node.value)
            assert type(value) is list
            assert all(type(row) is list for row in value)
            by_symbol[target.id] = cast("list[list[object]]", value)
    assert set(by_symbol) == wanted
    return {dataset_id: by_symbol[symbol] for dataset_id, symbol in _DATASET_SYMBOLS.items()}


def _rows(dataset_id: str) -> list[list[object]]:
    return copy.deepcopy(_source_rows_by_dataset()[dataset_id])


def _encode(rows: object) -> bytes:
    return json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _contract_sha256(dataset_id: str) -> str:
    return cast("str", _raw_contracts()[dataset_id]["contract_sha256"])


def _decode(dataset_id: str, rows: object | None = None) -> DecodedStaticResponseV1:
    return decode_static_value_response(
        _encode(_rows(dataset_id) if rows is None else rows),
        dataset_id=dataset_id,
        endpoint_contract_sha256=_contract_sha256(dataset_id),
    )


@lru_cache(maxsize=4)
def _cached_response(dataset_id: str) -> DecodedStaticResponseV1:
    return _decode(dataset_id)


def _reseal_field(item: DecodedStaticFieldV1, **changes: object) -> DecodedStaticFieldV1:
    forged = replace(item)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    object.__setattr__(
        forged,
        "field_sha256",
        static_decoder._canonical_sha256(static_decoder._field_identity(forged)),
    )
    return forged


def _reseal_cell(item: DecodedStaticCellV1, **changes: object) -> DecodedStaticCellV1:
    forged = replace(item)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    object.__setattr__(
        forged,
        "cell_sha256",
        static_decoder._canonical_sha256(static_decoder._cell_identity(forged)),
    )
    return forged


def _reseal_record(item: DecodedStaticRecordV1, **changes: object) -> DecodedStaticRecordV1:
    forged = replace(item)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    object.__setattr__(
        forged,
        "record_sha256",
        static_decoder._canonical_sha256(static_decoder._record_identity(forged)),
    )
    return forged


def _reseal_response(
    item: DecodedStaticResponseV1,
    **changes: object,
) -> DecodedStaticResponseV1:
    forged = replace(item)
    for name, value in changes.items():
        object.__setattr__(forged, name, value)
    object.__setattr__(
        forged,
        "fields_sha256",
        static_decoder._canonical_sha256([field.field_sha256 for field in forged.fields]),
    )
    object.__setattr__(
        forged,
        "records_sha256",
        static_decoder._canonical_sha256([record.record_sha256 for record in forged.records]),
    )
    object.__setattr__(
        forged,
        "cells_sha256",
        static_decoder._canonical_sha256([cell.cell_sha256 for cell in forged.cells]),
    )
    object.__setattr__(
        forged,
        "response_sha256",
        static_decoder._canonical_sha256(static_decoder._response_identity(forged)),
    )
    return forged


def _fully_reseal_cell_value(
    response: DecodedStaticResponseV1,
    *,
    cell_ordinal: int,
    value: object,
) -> DecodedStaticResponseV1:
    cells = list(response.cells)
    changed = replace(cells[cell_ordinal])
    canonical_json = static_decoder._canonical_json_text(value)
    object.__setattr__(changed, "canonical_json", canonical_json)
    object.__setattr__(changed, "presence_kind", static_decoder._presence_kind(value))
    object.__setattr__(changed, "value_kind", static_decoder._value_kind(value))
    object.__setattr__(
        changed,
        "value_sha256",
        hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
    )
    cells[cell_ordinal] = changed

    duplicate_values: Counter[tuple[int, str]] = Counter()
    sealed_cells: list[DecodedStaticCellV1] = []
    for cell in cells:
        duplicate_ordinal = duplicate_values[(cell.field_ordinal, cell.value_sha256)]
        duplicate_values[(cell.field_ordinal, cell.value_sha256)] += 1
        payload = static_decoder._cell_identity(cell)
        payload["duplicate_value_ordinal"] = duplicate_ordinal
        sealed_cells.append(
            DecodedStaticCellV1(
                **payload,
                cell_sha256=static_decoder._canonical_sha256(payload),
            )
        )

    rows: list[list[object]] = []
    records: list[DecodedStaticRecordV1] = []
    duplicate_records: Counter[str] = Counter()
    for record in response.records:
        row_cells = sealed_cells[
            record.cell_start_ordinal : record.cell_start_ordinal + record.cell_count
        ]
        row = [json.loads(cell.canonical_json) for cell in row_cells]
        rows.append(row)
        values_sha256 = static_decoder._canonical_sha256(row)
        missing, null, present_empty, scalar, container = static_decoder._record_counts(row)
        payload = {
            "cell_count": len(row_cells),
            "cell_start_ordinal": record.cell_start_ordinal,
            "container_value_count": container,
            "duplicate_record_ordinal": duplicate_records[values_sha256],
            "identifier": row[0],
            "missing_value_count": missing,
            "null_value_count": null,
            "present_empty_value_count": present_empty,
            "record_ordinal": record.record_ordinal,
            "scalar_value_count": scalar,
            "values_sha256": values_sha256,
        }
        duplicate_records[values_sha256] += 1
        records.append(
            DecodedStaticRecordV1(
                **payload,
                record_sha256=static_decoder._canonical_sha256(payload),
            )
        )

    headers = tuple(field.name for field in response.fields)
    raw_records = [dict(zip(headers, row, strict=True)) for row in rows]
    projected_records = [
        {name: record[name] for name in response.projected_fields} for record in raw_records
    ]
    parser_bytes = _encode(rows)
    presences = Counter(cell.presence_kind for cell in sealed_cells)
    kinds = Counter(cell.value_kind for cell in sealed_cells)
    forged = replace(response)
    updates: dict[str, object] = {
        "cells": tuple(sealed_cells),
        "records": tuple(records),
        "parser_input_length": len(parser_bytes),
        "parser_input_sha256": hashlib.sha256(parser_bytes).hexdigest(),
        "duplicate_record_count": sum(item.duplicate_record_ordinal > 0 for item in records),
        "duplicate_value_count": sum(item.duplicate_value_ordinal > 0 for item in sealed_cells),
        "missing_value_count": presences["missing"],
        "null_value_count": presences["null"],
        "present_empty_value_count": presences["empty_array"] + presences["empty_object"],
        "scalar_value_count": sum(
            kinds[name] for name in ("boolean", "integer", "number", "string")
        ),
        "container_value_count": kinds["array"] + kinds["object"],
        "normalized_output_sha256": static_decoder._canonical_sha256(
            {"headers": list(headers), "rows": rows}
        ),
        "source_rows_sha256": static_decoder._canonical_sha256(rows),
        "raw_records_sha256": static_decoder._canonical_sha256(raw_records),
        "projected_records_sha256": static_decoder._canonical_sha256(projected_records),
    }
    for name, item in updates.items():
        object.__setattr__(forged, name, item)
    object.__setattr__(
        forged,
        "records_sha256",
        static_decoder._canonical_sha256([record.record_sha256 for record in records]),
    )
    object.__setattr__(
        forged,
        "cells_sha256",
        static_decoder._canonical_sha256([cell.cell_sha256 for cell in sealed_cells]),
    )
    object.__setattr__(
        forged,
        "response_sha256",
        static_decoder._canonical_sha256(static_decoder._response_identity(forged)),
    )
    return forged


@pytest.fixture(scope="module", autouse=True)
def _warm_static_contracts() -> None:
    assert dict(pinned_static_decoder_contract_identities()) == {
        dataset_id: _contract_sha256(dataset_id) for dataset_id in sorted(_DATASET_SYMBOLS)
    }


@pytest.mark.parametrize(
    ("dataset_id", "record_count", "field_count"),
    [
        ("static_players", 5103, 5),
        ("static_teams", 30, 8),
        ("static_wnba_players", 1147, 5),
        ("static_wnba_teams", 13, 8),
    ],
)
def test_all_exact_static_packets_decode_with_full_contract_census(
    dataset_id: str,
    record_count: int,
    field_count: int,
) -> None:
    response = _cached_response(dataset_id)
    contract = _raw_contracts()[dataset_id]

    assert response.record_count == record_count
    assert response.field_count == field_count
    assert response.cell_count == record_count * field_count
    assert response.unique_identifier_count == record_count
    assert response.result_name == f"{contract['source_symbol']}_shape_1"
    assert response.container_kind == "nba_api_static_records"
    assert response.provider_result_ordinal == response.canonical_result_ordinal == 0
    assert response.source_rows_sha256 == contract["source_rows_sha256"]
    assert response.raw_records_sha256 == contract["raw_records_sha256"]
    assert response.projected_records_sha256 == contract["projected_records_sha256"]
    assert tuple(field.ordinal for field in response.fields) == tuple(range(field_count))
    assert tuple(record.record_ordinal for record in response.records) == tuple(range(record_count))
    assert tuple(cell.cell_ordinal for cell in response.cells) == tuple(
        range(record_count * field_count)
    )


def test_static_value_kinds_preserve_unicode_duplicates_and_empty_containers() -> None:
    players = _cached_response("static_players")
    teams = _cached_response("static_teams")

    assert any(
        any(ord(char) > 127 for char in cell.canonical_json)
        for cell in players.cells
        if cell.value_kind == "string"
    )
    assert {cell.value_kind for cell in players.cells} == {"boolean", "integer", "string"}
    assert teams.container_value_count == teams.record_count
    assert teams.present_empty_value_count == 10
    assert all(
        cell.value_kind == "array" for cell in teams.cells if cell.field_name == "championship_year"
    )
    assert any(cell.presence_kind == "empty_array" for cell in teams.cells)
    assert any(
        cell.value_kind == "array"
        and cell.presence_kind == "present"
        and json.loads(cell.canonical_json)
        for cell in teams.cells
    )
    assert players.duplicate_value_count > 0
    assert any(cell.duplicate_value_ordinal > 1 for cell in players.cells)
    assert players.duplicate_record_count == teams.duplicate_record_count == 0
    assert players.missing_value_count == players.null_value_count == 0


def test_public_projection_is_fixed_point_and_mutation_isolated() -> None:
    response = _cached_response("static_teams")
    validated = validate_decoded_static_response(response)
    detached = response.to_dict()
    cast("list[dict[str, object]]", detached["cells"])[0]["canonical_json"] = '"forged"'

    assert response.cells[0].canonical_json != '"forged"'
    assert validated == response
    assert validated is not response
    assert (
        response.to_canonical_bytes()
        == validate_decoded_static_response(response).to_canonical_bytes()
    )
    assert (
        decode_static_value_rows(
            _encode(_rows("static_teams")),
            dataset_id="static_teams",
            endpoint_contract_sha256=_contract_sha256("static_teams"),
        )
        == response.records
    )
    with pytest.raises(FrozenInstanceError):
        response.record_count = 0  # type: ignore[misc]


class _HostileString:
    def __hash__(self) -> int:
        return hash("static_teams")

    def __eq__(self, other: object) -> bool:
        return other == "static_teams"


@pytest.mark.parametrize(
    ("dataset_id", "digest", "error"),
    [
        ("foreign", "0" * 64, "differs from the exact frozen contract"),
        ("static_teams", "0" * 64, "differs from the exact frozen contract"),
        ("static_teams", "A" * 64, "lowercase full SHA-256"),
        (cast("str", True), "0" * 64, "nonempty exact string"),
        (cast("str", _HostileString()), "0" * 64, "nonempty exact string"),
    ],
)
def test_foreign_or_hostile_dataset_and_contract_identities_fail_closed(
    dataset_id: str,
    digest: str,
    error: str,
) -> None:
    with pytest.raises(IndependentStaticValueDecoderError, match=error):
        decode_static_value_response(
            _encode(_rows("static_teams")),
            dataset_id=dataset_id,
            endpoint_contract_sha256=digest,
        )


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        (b"", "byte length"),
        (b"\xff", "UTF-8 JSON"),
        (b"{}", "root must be an array"),
        (b"[{}]", "array of row arrays"),
        (b'[[1,"A","N",2000,"C","F","S",{"a":1,"a":2}]]', "duplicate"),
        (b"[[NaN]]", "non-finite"),
        (b"[[Infinity]]", "non-finite"),
        (b"[[" + b"9" * 5000 + b"]]", "number token exceeds"),
        (b"[" * 40 + b"0" + b"]" * 40, "depth exceeds"),
        (b'[["\\ud800"]]', "UTF-8 JSON"),
    ],
)
def test_malformed_duplicate_nonfinite_deep_and_huge_packets_fail_before_projection(
    raw: bytes,
    error: str,
) -> None:
    with pytest.raises(IndependentStaticValueDecoderError, match=error):
        decode_static_value_response(
            raw,
            dataset_id="static_teams",
            endpoint_contract_sha256=_contract_sha256("static_teams"),
        )


def test_noncanonical_whitespace_and_unicode_escape_packets_fail_closed() -> None:
    teams = _encode(_rows("static_teams"))
    players = _encode(_rows("static_players"))
    escaped = players.replace("ć".encode(), b"\\u0107", 1)
    assert escaped != players

    for raw in (b" " + teams, teams + b"\n", escaped):
        with pytest.raises(IndependentStaticValueDecoderError, match="canonical row JSON"):
            decode_static_value_response(
                raw,
                dataset_id="static_teams" if raw is not escaped else "static_players",
                endpoint_contract_sha256=_contract_sha256(
                    "static_teams" if raw is not escaped else "static_players"
                ),
            )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing_field", "row width"),
        ("additive_field", "row width"),
        ("null_field", "value type"),
        ("bool_identifier", "value type"),
        ("object_container", "value type"),
        ("empty_scalar", "content differs"),
        ("mixed_array", "content differs"),
        ("empty_array_drift", "content differs"),
        ("duplicate_identifier", "content differs"),
        ("reordered_records", "content differs"),
        ("missing_record", "row count"),
        ("additive_record", "row count"),
    ],
)
def test_missing_null_empty_mixed_duplicate_and_order_drift_fail_exact_content(
    mutation: str,
    error: str,
) -> None:
    rows = _rows("static_teams")
    if mutation == "missing_field":
        rows[0].pop()
    elif mutation == "additive_field":
        rows[0].append("future")
    elif mutation == "null_field":
        rows[0][1] = None
    elif mutation == "bool_identifier":
        rows[0][0] = True
    elif mutation == "object_container":
        rows[0][7] = {"year": 1958}
    elif mutation == "empty_scalar":
        rows[0][1] = ""
    elif mutation == "mixed_array":
        rows[0][7] = [1958, "future"]
    elif mutation == "empty_array_drift":
        target = next(row for row in rows if row[7])
        target[7] = []
    elif mutation == "duplicate_identifier":
        rows[1][0] = rows[0][0]
    elif mutation == "reordered_records":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "missing_record":
        rows.pop()
    elif mutation == "additive_record":
        rows.append(copy.deepcopy(rows[-1]))
    else:
        raise AssertionError(mutation)

    with pytest.raises(IndependentStaticValueDecoderError, match=error):
        _decode("static_teams", rows)


@pytest.mark.parametrize(
    ("limit_name", "limit", "error"),
    [
        ("MAX_PARSER_INPUT_BYTES", 100, "byte length"),
        ("MAX_STATIC_RECORDS", 1, "row arrays"),
        ("MAX_STATIC_CELLS", 8, "cell count exceeds"),
        ("MAX_JSON_CONTAINER_ITEMS", 10, "container item count exceeds"),
        ("MAX_JSON_NODES", 10, "node count exceeds"),
        ("MAX_JSON_STRING_BYTES", 2, "string token exceeds"),
        ("MAX_JSON_TOTAL_STRING_BYTES", 20, "cumulative string bytes exceed"),
        ("MAX_CANONICAL_VALUE_BYTES", 2, "canonical value bytes exceed"),
    ],
)
def test_parser_and_cumulative_resource_bounds_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit: int,
    error: str,
) -> None:
    monkeypatch.setattr(static_decoder, limit_name, limit)
    with pytest.raises(IndependentStaticValueDecoderError, match=error):
        _decode("static_teams")


def test_public_types_and_boolean_resource_fields_fail_at_reconstruction() -> None:
    response = _cached_response("static_teams")
    with pytest.raises(IndependentStaticValueDecoderError, match="exact public contract type"):
        validate_decoded_static_response(response.to_dict())
    forged = _reseal_response(response, record_count=True)
    with pytest.raises(IndependentStaticValueDecoderError, match="bounded exact integer"):
        validate_decoded_static_response(forged)


@pytest.mark.parametrize("inventory", ["fields", "records", "cells"])
def test_foreign_nested_public_dto_types_fail_before_inventory_use(inventory: str) -> None:
    response = _cached_response("static_teams")
    forged = replace(response)
    original = cast("tuple[object, ...]", getattr(response, inventory))
    object.__setattr__(forged, inventory, (object(), *original[1:]))

    with pytest.raises(IndependentStaticValueDecoderError, match=f"static {inventory[:-1]} type"):
        validate_decoded_static_response(forged)


def test_hostile_response_dataset_equality_fails_before_mapping_lookup() -> None:
    response = _cached_response("static_teams")
    forged = replace(response)
    object.__setattr__(forged, "dataset_id", _HostileString())

    with pytest.raises(IndependentStaticValueDecoderError, match="nonempty exact string"):
        validate_decoded_static_response(forged)


@pytest.mark.parametrize("dataset_id", sorted(_DATASET_SYMBOLS))
def test_same_type_cell_tamper_fails_exact_content_for_every_dataset(dataset_id: str) -> None:
    rows = _rows(dataset_id)
    assert type(rows[0][1]) is str
    rows[0][1] = cast("str", rows[0][1]) + " FORGED"

    with pytest.raises(IndependentStaticValueDecoderError, match="content differs"):
        _decode(dataset_id, rows)


def test_fully_resealed_foreign_value_snapshot_still_fails_pinned_content() -> None:
    response = _cached_response("static_teams")
    target = next(cell for cell in response.cells if cell.field_name == "abbreviation")
    forged = _fully_reseal_cell_value(
        response,
        cell_ordinal=target.cell_ordinal,
        value="FORGED",
    )

    assert forged.parser_input_sha256 != response.parser_input_sha256
    assert forged.source_rows_sha256 != response.source_rows_sha256
    assert forged.records_sha256 != response.records_sha256
    assert forged.cells_sha256 != response.cells_sha256
    with pytest.raises(IndependentStaticValueDecoderError, match="content differs"):
        validate_decoded_static_response(forged)


@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("cell_record", "record/field binding"),
        ("cell_field", "record/field binding"),
        ("cell_duplicate", "duplicate-value ordinal"),
        ("record_duplicate", "exact cell values"),
        ("record_identifier", "exact cell values"),
        ("record_slice", "cell slice"),
        ("field_name", "frozen contract"),
        ("parser_sha", "denominators differ"),
        ("source_sha", "digests differ"),
        ("missing_presence", "presence/type identity"),
    ],
)
def test_fully_resealed_binding_denominator_and_presence_tampering_is_rejected(
    kind: str,
    error: str,
) -> None:
    response = _cached_response("static_teams")
    forged = response
    if kind.startswith("cell_") or kind == "missing_presence":
        target = response.cells[0]
        changes: dict[str, object] = {
            "cell_record": {"record_ordinal": 1},
            "cell_field": {"field_ordinal": 1},
            "cell_duplicate": {"duplicate_value_ordinal": 99},
            "missing_presence": {"presence_kind": "missing"},
        }[kind]
        forged_cell = _reseal_cell(target, **changes)
        cells = (forged_cell, *response.cells[1:])
        forged = _reseal_response(response, cells=cells)
    elif kind.startswith("record_"):
        target_record = response.records[0]
        changes = {
            "record_duplicate": {"duplicate_record_ordinal": 1},
            "record_identifier": {"identifier": 1},
            "record_slice": {"cell_start_ordinal": 1},
        }[kind]
        forged_record = _reseal_record(target_record, **changes)
        records = (forged_record, *response.records[1:])
        forged = _reseal_response(response, records=records)
    elif kind == "field_name":
        target_field = response.fields[0]
        forged_field = _reseal_field(target_field, name="forged")
        fields = (forged_field, *response.fields[1:])
        forged = _reseal_response(response, fields=fields)
    elif kind == "parser_sha":
        forged = _reseal_response(response, parser_input_sha256="0" * 64)
    elif kind == "source_sha":
        forged = _reseal_response(response, source_rows_sha256="0" * 64)
    else:
        raise AssertionError(kind)

    with pytest.raises(IndependentStaticValueDecoderError, match=error):
        validate_decoded_static_response(forged)


def test_contract_resource_digest_tampering_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_bytes = Path.read_bytes
    original = original_read_bytes(_RESOURCE)
    forged = original.replace(
        b'"static_contracts_sha256":"ccd209d3',
        b'"static_contracts_sha256":"0cd209d3',
        1,
    )
    assert forged != original

    def forged_read_bytes(path: Path) -> bytes:
        return forged if path == _RESOURCE else original_read_bytes(path)

    static_decoder._pinned_static_contracts.cache_clear()
    monkeypatch.setattr(Path, "read_bytes", forged_read_bytes)
    with pytest.raises(IndependentStaticValueDecoderError, match="differs from its exact pin"):
        pinned_static_decoder_contract_identities()
    monkeypatch.undo()
    static_decoder._pinned_static_contracts.cache_clear()
    assert len(pinned_static_decoder_contract_identities()) == 4


def test_self_resealed_contract_resource_still_fails_external_static_pin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read_bytes = Path.read_bytes
    payload = json.loads(original_read_bytes(_RESOURCE))
    static_contracts = cast("dict[str, dict[str, object]]", payload["static_contracts"])
    contract = static_contracts["static_teams"]
    contract["row_count"] = cast("int", contract["row_count"]) + 1
    contract_body = dict(contract)
    contract_body.pop("contract_sha256")
    contract["contract_sha256"] = static_decoder._canonical_sha256(contract_body)
    payload["static_contracts_sha256"] = static_decoder._canonical_sha256(static_contracts)
    forged = _encode(payload)

    def forged_read_bytes(path: Path) -> bytes:
        return forged if path == _RESOURCE else original_read_bytes(path)

    static_decoder._pinned_static_contracts.cache_clear()
    monkeypatch.setattr(Path, "read_bytes", forged_read_bytes)
    with pytest.raises(IndependentStaticValueDecoderError, match="differs from its exact pin"):
        pinned_static_decoder_contract_identities()
    monkeypatch.undo()
    static_decoder._pinned_static_contracts.cache_clear()
    assert len(pinned_static_decoder_contract_identities()) == 4


def test_module_imports_no_provider_adapter_staging_or_orchestration_dependencies() -> None:
    source_path = Path(static_decoder.__file__).resolve()
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
        "nbadb.schemas",
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
name = 'isolated_independent_static_value_decoder'
spec = importlib.util.spec_from_file_location(name, path)
if spec is None or spec.loader is None:
    raise SystemExit('missing module spec')
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
forbidden = (
    'nba_api',
    'polars',
    'nbadb.extract',
    'nbadb.orchestrate',
    'nbadb.schemas',
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
