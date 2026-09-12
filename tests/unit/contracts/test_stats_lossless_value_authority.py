from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace

import polars as pl
import pytest

from nbadb.contracts import stats_lossless_value_authority as authority_module
from nbadb.contracts.public_value_types import (
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.stats_lossless_value_authority import (
    MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES,
    STATS_LOSSLESS_RECORD_COLUMNS,
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
    STATS_LOSSLESS_SOURCE_SCHEMA_SHA256,
    StatsLosslessManifestV1,
    StatsLosslessRecordV1,
    StatsLosslessResultV1,
    StatsLosslessValueAuthorityError,
    StatsLosslessValueAuthorityReceiptV1,
    StatsLosslessValueAuthorityV1,
    build_stats_lossless_value_authority,
    canonical_ordered_root_sha256,
    canonical_sha256,
    stats_lossless_result_declaration_value,
)
from nbadb.schemas.raw import nba_api_stats_lossless_record as schema_module
from nbadb.schemas.raw.nba_api_stats_lossless_record import (
    RawNbaApiStatsLosslessRecordSchema,
)

_RAW = "a" * 64
_RAW_SECOND = "8" * 64
_OBSERVATION_RECORD = "b" * 64
_OBSERVATION = "c" * 64
_OCCURRENCE = "d" * 64
_ROUTE_AUTHORITY = "e" * 64
_COMMITTED = "f" * 64
_RESPONSE = "1" * 64
_PROVIDER = "2" * 64
_CONTRACT = "3" * 64
_PARAMETERS = "4" * 64
_RESPONSE_MODE = "5" * 64
_PARSER_INPUT = "6" * 64
_CANONICAL_PAYLOAD = "7" * 64
_ROUTE_ID = "example:stg_nba_api_lossless_result_cells:1"
_ENDPOINT = "example"
_GLOBAL_ANOMALIES = ("additive_header",)


def _unsafe_canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unsafe_reseal_record_row(
    record: StatsLosslessRecordV1,
    *,
    row_changes: dict[str, object],
    source_changes: dict[str, object],
) -> dict[str, object]:
    row = record.to_row()
    row.update(row_changes)
    source = record.source_row()
    source.update(source_changes)
    row["source_row_sha256"] = _unsafe_canonical_sha256(source)
    identity = {
        "schema_version": row["schema_version"],
        "kind": StatsLosslessRecordV1.kind,
        **{
            column: row[column]
            for column in STATS_LOSSLESS_RECORD_COLUMNS[1:]
            if column != "record_sha256"
        },
    }
    row["record_sha256"] = _unsafe_canonical_sha256(identity)
    return row


def _unsafe_reseal_result_row(
    result: StatsLosslessResultV1,
    *,
    changes: dict[str, object],
) -> dict[str, object]:
    row = result.to_row()
    row.update(changes)
    identity = {
        "schema_version": row["schema_version"],
        "kind": StatsLosslessResultV1.kind,
        **{
            name: value
            for name, value in row.items()
            if name not in {"schema_version", "result_sha256"}
        },
    }
    row["result_sha256"] = _unsafe_canonical_sha256(identity)
    return row


def _record(
    *,
    raw_authority_bundle_sha256: str = _RAW,
    global_ordinal: int,
    local_ordinal: int,
    record_kind: str,
    header_name: str | None = None,
    header_ordinal: int | None = None,
    row_ordinal: int | None = None,
    value: object,
    canonical_payload_sha256: str = _CANONICAL_PAYLOAD,
    response_state: str = "legacy_present_nonempty",
    legacy_envelope_name: str | None = "resultSets",
    global_anomaly_codes: tuple[str, ...] = _GLOBAL_ANOMALIES,
) -> StatsLosslessRecordV1:
    return StatsLosslessRecordV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        observation_record_sha256=_OBSERVATION_RECORD,
        observation_sha256=_OBSERVATION,
        owner_kind="result_occurrence",
        occurrence_sha256=_OCCURRENCE,
        route_id=_ROUTE_ID,
        route_authority_sha256=_ROUTE_AUTHORITY,
        committed_receipt_sha256=_COMMITTED,
        response_receipt_sha256=_RESPONSE,
        provider_authority_sha256=_PROVIDER,
        endpoint_contract_sha256=_CONTRACT,
        response_mode_authority_sha256=_RESPONSE_MODE,
        parser_input_sha256=_PARSER_INPUT,
        canonical_payload_sha256=canonical_payload_sha256,
        parameters_sha256=_PARAMETERS,
        endpoint_id=_ENDPOINT,
        endpoint_slug=_ENDPOINT,
        response_state=response_state,
        legacy_envelope_name=legacy_envelope_name,
        global_record_ordinal=global_ordinal,
        occurrence_record_ordinal=local_ordinal,
        response_record_ordinal=None,
        record_kind=record_kind,  # type: ignore[arg-type]
        result_set_name="Main",
        result_set_occurrence=0,
        provider_result_ordinal=0,
        expected_result_ordinal=0,
        canonical_result_ordinal=0,
        header_name=header_name,
        header_ordinal=header_ordinal,
        row_ordinal=row_ordinal,
        value_present=True,
        value=value,
        global_anomaly_codes=global_anomaly_codes,
    )


def _authority_rows(
    *,
    raw_authority_bundle_sha256: str = _RAW,
) -> tuple[
    tuple[StatsLosslessRecordV1, ...],
    StatsLosslessResultV1,
    StatsLosslessManifestV1,
]:
    raw_headers = ["A", "B"]
    raw_rows = [[1, 2]]
    output_sha256 = canonical_sha256(
        {"headers": raw_headers, "rows": raw_rows, "anomalies": ["additive_header"]}
    )
    declaration = stats_lossless_result_declaration_value(
        presence="present",
        expected_headers=["A"],
        anomaly_codes=["additive_header"],
        normalized_output_sha256=output_sha256,
        header_record_count=2,
        raw_row_occurrence_count=1,
        sequence_row_count=1,
        raw_cell_count=2,
    )
    values = (
        ("result_set", None, None, None, declaration),
        ("raw_headers", None, None, None, raw_headers),
        ("raw_rows", None, None, None, raw_rows),
        ("header", "A", 0, None, "A"),
        ("header", "B", 1, None, "B"),
        ("row", None, None, 0, [1, 2]),
        ("cell", "A", 0, 0, 1),
        ("cell", "B", 1, 0, 2),
    )
    records = tuple(
        _record(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            global_ordinal=ordinal,
            local_ordinal=ordinal,
            record_kind=kind,
            header_name=header_name,
            header_ordinal=header_ordinal,
            row_ordinal=row_ordinal,
            value=value,
        )
        for ordinal, (kind, header_name, header_ordinal, row_ordinal, value) in enumerate(values)
    )
    result = StatsLosslessResultV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        observation_record_sha256=_OBSERVATION_RECORD,
        observation_sha256=_OBSERVATION,
        occurrence_sha256=_OCCURRENCE,
        route_id=_ROUTE_ID,
        route_authority_sha256=_ROUTE_AUTHORITY,
        committed_receipt_sha256=_COMMITTED,
        response_receipt_sha256=_RESPONSE,
        result_ordinal=0,
        result_set_name="Main",
        result_set_occurrence=0,
        provider_result_ordinal=0,
        expected_result_ordinal=0,
        canonical_result_ordinal=0,
        occurrence_canonical_result_ordinal=None,
        presence="present",
        expected_headers=["A"],
        raw_headers=raw_headers,
        raw_rows=raw_rows,
        header_record_count=2,
        raw_row_occurrence_count=1,
        sequence_row_count=1,
        raw_cell_count=2,
        anomaly_codes=["additive_header"],
        normalized_output_sha256=output_sha256,
        first_global_record_ordinal=0,
        records=records,
    )
    manifest = StatsLosslessManifestV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        observation_record_sha256=_OBSERVATION_RECORD,
        observation_sha256=_OBSERVATION,
        route_id=_ROUTE_ID,
        route_authority_sha256=_ROUTE_AUTHORITY,
        committed_receipt_sha256=_COMMITTED,
        response_receipt_sha256=_RESPONSE,
        endpoint_id=_ENDPOINT,
        endpoint_slug=_ENDPOINT,
        provider_authority_sha256=_PROVIDER,
        endpoint_contract_sha256=_CONTRACT,
        parameters_sha256=_PARAMETERS,
        global_anomaly_codes=_GLOBAL_ANOMALIES,
        provider_result_set_count=1,
        expected_result_set_count=1,
        results=[result],
        records=records,
    )
    return records, result, manifest


def _response_residual_records(
    *,
    raw_authority_bundle_sha256: str = _RAW,
    payload: object,
    global_start: int,
    global_anomalies: tuple[str, ...],
) -> tuple[StatsLosslessRecordV1, ...]:
    canonical_payload_sha256 = canonical_sha256(payload)

    def build_record(**values: object) -> StatsLosslessRecordV1:
        return StatsLosslessRecordV1.build(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            observation_record_sha256=_OBSERVATION_RECORD,
            observation_sha256=_OBSERVATION,
            owner_kind="response_residual",
            occurrence_sha256=None,
            route_id=_ROUTE_ID,
            route_authority_sha256=_ROUTE_AUTHORITY,
            committed_receipt_sha256=_COMMITTED,
            response_receipt_sha256=_RESPONSE,
            provider_authority_sha256=_PROVIDER,
            endpoint_contract_sha256=_CONTRACT,
            response_mode_authority_sha256=_RESPONSE_MODE,
            parser_input_sha256=_PARSER_INPUT,
            canonical_payload_sha256=canonical_payload_sha256,
            parameters_sha256=_PARAMETERS,
            endpoint_id=_ENDPOINT,
            endpoint_slug=_ENDPOINT,
            response_state="unknown_result_envelope",
            legacy_envelope_name=None,
            result_set_name=None,
            result_set_occurrence=None,
            provider_result_ordinal=None,
            expected_result_ordinal=None,
            canonical_result_ordinal=None,
            global_anomaly_codes=global_anomalies,
            **values,  # type: ignore[arg-type]
        )

    records = [
        build_record(
            global_record_ordinal=global_start,
            occurrence_record_ordinal=None,
            response_record_ordinal=0,
            record_kind="response",
        )
    ]
    node_specs: list[dict[str, object]] = []

    def path(tokens: tuple[str | int, ...]) -> str:
        return "$" + "".join(
            f"[{token}]" if type(token) is int else f"[{json.dumps(token, ensure_ascii=False)}]"
            for token in tokens
        )

    def visit(
        value: object,
        *,
        parent_node_ordinal: int | None,
        tokens: tuple[str | int, ...],
        object_key: str | None,
        object_key_ordinal: int | None,
        array_ordinal: int | None,
    ) -> None:
        node_ordinal = len(node_specs)
        node_specs.append(
            {
                "value": value,
                "node_ordinal": node_ordinal,
                "parent_node_ordinal": parent_node_ordinal,
                "json_path": path(tokens),
                "parent_json_path": (None if parent_node_ordinal is None else path(tokens[:-1])),
                "depth": len(tokens),
                "object_key": object_key,
                "object_key_ordinal": object_key_ordinal,
                "array_ordinal": array_ordinal,
            }
        )
        if type(value) is dict:
            for ordinal, (key, child) in enumerate(value.items()):
                visit(
                    child,
                    parent_node_ordinal=node_ordinal,
                    tokens=(*tokens, key),
                    object_key=key,
                    object_key_ordinal=ordinal,
                    array_ordinal=None,
                )
        elif type(value) is list:
            for ordinal, child in enumerate(value):
                visit(
                    child,
                    parent_node_ordinal=node_ordinal,
                    tokens=(*tokens, ordinal),
                    object_key=None,
                    object_key_ordinal=None,
                    array_ordinal=ordinal,
                )

    visit(
        payload,
        parent_node_ordinal=None,
        tokens=(),
        object_key=None,
        object_key_ordinal=None,
        array_ordinal=None,
    )
    for response_ordinal, spec in enumerate(node_specs, start=1):
        value = spec["value"]
        nonempty_container = type(value) in {dict, list} and bool(value)
        records.append(
            build_record(
                global_record_ordinal=global_start + response_ordinal,
                occurrence_record_ordinal=None,
                response_record_ordinal=response_ordinal,
                record_kind="json_node",
                node_ordinal=spec["node_ordinal"],
                parent_node_ordinal=spec["parent_node_ordinal"],
                json_path=spec["json_path"],
                parent_json_path=spec["parent_json_path"],
                depth=spec["depth"],
                object_key=spec["object_key"],
                object_key_ordinal=spec["object_key_ordinal"],
                array_ordinal=spec["array_ordinal"],
                value_present=not nonempty_container,
                value=value,
                explicit_presence_kind=("present" if nonempty_container else None),
                explicit_value_kind=(
                    "object"
                    if type(value) is dict and nonempty_container
                    else "array"
                    if type(value) is list and nonempty_container
                    else None
                ),
            )
        )
    return tuple(records)


def _hybrid_authority(
    *,
    raw_authority_bundle_sha256: str = _RAW,
) -> StatsLosslessValueAuthorityV1:
    payload = {"flags": [True, None], "meta": {"season": "2025-26"}}
    payload_sha256 = canonical_sha256(payload)
    global_anomalies = ("additive_header", "unknown_dynamic_response")
    base_records, _base_result, _base_manifest = _authority_rows(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256
    )
    occurrence_records = tuple(
        _record(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            global_ordinal=ordinal,
            local_ordinal=ordinal,
            record_kind=record.record_kind,
            header_name=record.header_name,
            header_ordinal=record.header_ordinal,
            row_ordinal=record.row_ordinal,
            value=record.value(),
            canonical_payload_sha256=payload_sha256,
            response_state="unknown_result_envelope",
            legacy_envelope_name=None,
            global_anomaly_codes=global_anomalies,
        )
        for ordinal, record in enumerate(base_records)
    )
    raw_headers = ["A", "B"]
    raw_rows = [[1, 2]]
    output_sha256 = canonical_sha256(
        {"headers": raw_headers, "rows": raw_rows, "anomalies": ["additive_header"]}
    )
    result = StatsLosslessResultV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        observation_record_sha256=_OBSERVATION_RECORD,
        observation_sha256=_OBSERVATION,
        occurrence_sha256=_OCCURRENCE,
        route_id=_ROUTE_ID,
        route_authority_sha256=_ROUTE_AUTHORITY,
        committed_receipt_sha256=_COMMITTED,
        response_receipt_sha256=_RESPONSE,
        result_ordinal=0,
        result_set_name="Main",
        result_set_occurrence=0,
        provider_result_ordinal=0,
        expected_result_ordinal=0,
        canonical_result_ordinal=0,
        occurrence_canonical_result_ordinal=None,
        presence="present",
        expected_headers=["A"],
        raw_headers=raw_headers,
        raw_rows=raw_rows,
        header_record_count=2,
        raw_row_occurrence_count=1,
        sequence_row_count=1,
        raw_cell_count=2,
        anomaly_codes=["additive_header"],
        normalized_output_sha256=output_sha256,
        first_global_record_ordinal=0,
        records=occurrence_records,
    )
    residual_records = _response_residual_records(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        payload=payload,
        global_start=len(occurrence_records),
        global_anomalies=global_anomalies,
    )
    return build_stats_lossless_value_authority(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        observation_record_sha256=_OBSERVATION_RECORD,
        observation_sha256=_OBSERVATION,
        route_id=_ROUTE_ID,
        route_authority_sha256=_ROUTE_AUTHORITY,
        committed_receipt_sha256=_COMMITTED,
        response_receipt_sha256=_RESPONSE,
        endpoint_id=_ENDPOINT,
        endpoint_slug=_ENDPOINT,
        provider_authority_sha256=_PROVIDER,
        endpoint_contract_sha256=_CONTRACT,
        parameters_sha256=_PARAMETERS,
        global_anomaly_codes=global_anomalies,
        provider_result_set_count=1,
        expected_result_set_count=1,
        results=(result,),
        records=(*occurrence_records, *residual_records),
    )


def _build_manifest(
    *,
    results: list[StatsLosslessResultV1],
    records: tuple[StatsLosslessRecordV1, ...],
    provider_result_set_count: int = 1,
    expected_result_set_count: int = 1,
    global_anomaly_codes: tuple[str, ...] = _GLOBAL_ANOMALIES,
) -> StatsLosslessManifestV1:
    return StatsLosslessManifestV1.build(
        raw_authority_bundle_sha256=_RAW,
        observation_record_sha256=_OBSERVATION_RECORD,
        observation_sha256=_OBSERVATION,
        route_id=_ROUTE_ID,
        route_authority_sha256=_ROUTE_AUTHORITY,
        committed_receipt_sha256=_COMMITTED,
        response_receipt_sha256=_RESPONSE,
        endpoint_id=_ENDPOINT,
        endpoint_slug=_ENDPOINT,
        provider_authority_sha256=_PROVIDER,
        endpoint_contract_sha256=_CONTRACT,
        parameters_sha256=_PARAMETERS,
        global_anomaly_codes=global_anomaly_codes,
        provider_result_set_count=provider_result_set_count,
        expected_result_set_count=expected_result_set_count,
        results=results,
        records=records,
    )


def test_single_physical_relation_round_trips_and_has_one_strict_schema() -> None:
    records, result, manifest = _authority_rows()
    assert tuple(StatsLosslessRecordV1.from_row(row.to_row()) for row in records) == records
    assert StatsLosslessResultV1.from_row(result.to_row()) == result
    assert StatsLosslessManifestV1.from_row(manifest.to_row()) == manifest
    frame = pl.DataFrame(
        [row.to_row() for row in records],
        schema_overrides={
            "response_record_ordinal": pl.Int64,
            "node_ordinal": pl.Int64,
            "parent_node_ordinal": pl.Int64,
            "json_path": pl.String,
            "parent_json_path": pl.String,
            "depth": pl.Int64,
            "object_key": pl.String,
            "object_key_ordinal": pl.Int64,
            "array_ordinal": pl.Int64,
        },
    )
    assert RawNbaApiStatsLosslessRecordSchema.validate(frame).shape == frame.shape
    assert schema_module.__all__ == ["RawNbaApiStatsLosslessRecordSchema"]
    assert tuple(RawNbaApiStatsLosslessRecordSchema.to_schema().columns) == (
        STATS_LOSSLESS_RECORD_COLUMNS
    )
    assert STATS_LOSSLESS_RECORD_SCHEMA_SHA256 == (
        "f767f834d3e9a7b77d48602627b7eeba95ecd1427b7e14d5bafa3bf6bb63d621"
    )
    assert STATS_LOSSLESS_SOURCE_SCHEMA_SHA256 == (
        "c6b54e0329840af27ace653ec8c6a98c65e9fb03d98f74c6843a220cae04d526"
    )
    assert manifest.response_residual_record_count == 0
    assert manifest.response_residual_records_sha256 == canonical_ordered_root_sha256(
        kind="stats_lossless_response_residual_records_v1",
        count=0,
        values=(),
    )


def test_production_builder_closes_hybrid_occurrence_and_response_residual() -> None:
    authority = _hybrid_authority()
    assert authority.receipt.response_residual_record_count == 7
    assert authority.manifest.response_residual_record_count == 7
    assert [unit.unit_kind for unit in authority.expected_unit_inventory.units] == [
        "result_occurrence",
        "response_residual",
    ]
    assert all(
        unit.raw_authority_bundle_sha256 == _RAW for unit in authority.expected_unit_inventory.units
    )
    assert authority.expected_unit_inventory.raw_authority_bundle_sha256 == _RAW
    assert [
        assignment.representation_kind for assignment in authority.representation_assignments
    ] == ["stats_lossless_records_v1", "response_lossless_records_v1"]
    assert all(
        assignment.raw_authority_bundle_sha256 == _RAW
        and assignment.source_input_kind == "parser_input_body"
        for assignment in authority.representation_assignments
    )
    assert (
        tuple(StatsLosslessRecordV1.from_row(record.to_row()) for record in authority.records)
        == authority.records
    )
    frame = pl.DataFrame(
        authority.public_rows(),
        schema_overrides={"legacy_envelope_name": pl.String},
    )
    assert RawNbaApiStatsLosslessRecordSchema.validate(frame).shape == frame.shape


def test_distinct_bundles_reuse_local_zero_and_preserve_dto_pandera_parity() -> None:
    first = _hybrid_authority(raw_authority_bundle_sha256=_RAW)
    second = _hybrid_authority(raw_authority_bundle_sha256=_RAW_SECOND)

    assert first.expected_unit_inventory.units[0].unit_ordinal == 0
    assert second.expected_unit_inventory.units[0].unit_ordinal == 0
    assert first.expected_unit_inventory.unit_root_sha256 != (
        second.expected_unit_inventory.unit_root_sha256
    )
    assert first.expected_unit_inventory.inventory_sha256 != (
        second.expected_unit_inventory.inventory_sha256
    )
    assert (
        ExpectedValueUnitInventoryV1.from_row(first.expected_unit_inventory.to_row())
        == first.expected_unit_inventory
    )
    assert (
        ExpectedValueUnitInventoryV1.from_row(second.expected_unit_inventory.to_row())
        == second.expected_unit_inventory
    )
    assert tuple(
        ValueRepresentationAssignmentV1.from_row(assignment.to_row())
        for assignment in (*first.representation_assignments, *second.representation_assignments)
    ) == (*first.representation_assignments, *second.representation_assignments)
    frame = pl.DataFrame(
        [*first.public_rows(), *second.public_rows()],
        schema_overrides={"legacy_envelope_name": pl.String},
    )
    assert RawNbaApiStatsLosslessRecordSchema.validate(frame).shape == frame.shape


def test_empty_stats_inventory_is_scoped_without_fabricated_fixed_zero_unit() -> None:
    first = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_RAW,
        units=(),
    )
    second = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_RAW_SECOND,
        units=(),
    )

    assert first.units == second.units == ()
    assert first.unit_count == second.unit_count == 0
    assert first.unit_root_sha256 != second.unit_root_sha256
    assert first.inventory_sha256 != second.inventory_sha256


def test_stats_authority_rejects_foreign_source_input_assignments() -> None:
    assert (
        "source_input_kind"
        not in inspect.signature(build_stats_lossless_value_authority).parameters
    )
    authority = _hybrid_authority()
    bodyless_assignments = tuple(
        ValueRepresentationAssignmentV1.build(
            expected_unit=unit,
            source_input_kind="declared_bodyless_packet",
            representation_kind=assignment.representation_kind,
        )
        for unit, assignment in zip(
            authority.expected_unit_inventory.units,
            authority.representation_assignments,
            strict=True,
        )
    )

    with pytest.raises(StatsLosslessValueAuthorityError, match="Raw-V2 parser-input source"):
        replace(authority, representation_assignments=bodyless_assignments)


def test_stats_authority_rejects_cross_bundle_coordinated_unit_reseal() -> None:
    authority = _hybrid_authority()
    foreign_units = tuple(
        ExpectedValueUnitV1.build(
            raw_authority_bundle_sha256=_RAW_SECOND,
            unit_ordinal=unit.unit_ordinal,
            observation_sha256=unit.observation_sha256,
            observation_ordinal=unit.observation_ordinal,
            unit_kind=unit.unit_kind,
            occurrence_sha256=unit.occurrence_sha256,
            occurrence_ordinal=unit.occurrence_ordinal,
        )
        for unit in authority.expected_unit_inventory.units
    )
    foreign_inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_RAW_SECOND,
        units=foreign_units,
    )
    foreign_assignments = tuple(
        ValueRepresentationAssignmentV1.build(
            expected_unit=unit,
            source_input_kind="parser_input_body",
            representation_kind=assignment.representation_kind,
        )
        for unit, assignment in zip(
            foreign_units,
            authority.representation_assignments,
            strict=True,
        )
    )

    with pytest.raises(
        StatsLosslessValueAuthorityError,
        match="expected-unit representations are incomplete",
    ):
        replace(
            authority,
            expected_unit_inventory=foreign_inventory,
            representation_assignments=foreign_assignments,
        )


def test_production_builder_closes_residual_only_zero_result_denominators() -> None:
    records = _response_residual_records(
        payload={"meta": []},
        global_start=0,
        global_anomalies=("unknown_dynamic_response",),
    )
    authority = build_stats_lossless_value_authority(
        raw_authority_bundle_sha256=_RAW,
        observation_record_sha256=_OBSERVATION_RECORD,
        observation_sha256=_OBSERVATION,
        route_id=_ROUTE_ID,
        route_authority_sha256=_ROUTE_AUTHORITY,
        committed_receipt_sha256=_COMMITTED,
        response_receipt_sha256=_RESPONSE,
        endpoint_id=_ENDPOINT,
        endpoint_slug=_ENDPOINT,
        provider_authority_sha256=_PROVIDER,
        endpoint_contract_sha256=_CONTRACT,
        parameters_sha256=_PARAMETERS,
        global_anomaly_codes=("unknown_dynamic_response",),
        provider_result_set_count=0,
        expected_result_set_count=0,
        results=(),
        records=records,
    )
    assert authority.manifest.result_count == 0
    assert authority.manifest.occurrence_count == 0
    assert authority.manifest.response_residual_record_count == 3
    assert authority.expected_unit_inventory.units[0].unit_kind == "response_residual"
    assert all(
        unit.unit_kind != "response_fixed_zero" for unit in authority.expected_unit_inventory.units
    )
    assert authority.representation_assignments[0].representation_kind == (
        "response_lossless_records_v1"
    )


@pytest.mark.parametrize(
    ("target", "row_changes", "source_changes"),
    [
        (0, {"occurrence_sha256": "8" * 64}, {}),
        (0, {"representation_kind": "stats_lossless_records_v1"}, {}),
        (
            0,
            {"result_set_name": "Main"},
            {"result_set_name": "Main"},
        ),
        (1, {"parent_node_ordinal": 0}, {"parent_node_ordinal": 0}),
    ],
)
def test_record_owner_discriminator_and_nullable_identity_are_exact(
    target: int,
    row_changes: dict[str, object],
    source_changes: dict[str, object],
) -> None:
    records = _response_residual_records(
        payload={"meta": []},
        global_start=0,
        global_anomalies=("unknown_dynamic_response",),
    )
    row = _unsafe_reseal_record_row(
        records[target], row_changes=row_changes, source_changes=source_changes
    )
    with pytest.raises(StatsLosslessValueAuthorityError):
        StatsLosslessRecordV1.from_row(row)


@pytest.mark.parametrize(
    ("target", "row_changes", "source_changes"),
    [
        (0, {"response_record_ordinal": 1}, {}),
        (2, {"node_ordinal": 2}, {"node_ordinal": 2}),
        (2, {"json_path": '$["forged"]'}, {"json_path": '$["forged"]'}),
    ],
)
def test_manifest_rederives_response_residual_partition_after_self_reseal(
    target: int,
    row_changes: dict[str, object],
    source_changes: dict[str, object],
) -> None:
    records = list(
        _response_residual_records(
            payload={"meta": []},
            global_start=0,
            global_anomalies=("unknown_dynamic_response",),
        )
    )
    records[target] = StatsLosslessRecordV1.from_row(
        _unsafe_reseal_record_row(
            records[target], row_changes=row_changes, source_changes=source_changes
        )
    )
    with pytest.raises(StatsLosslessValueAuthorityError, match="residual|partition"):
        _build_manifest(
            results=[],
            records=tuple(records),
            provider_result_set_count=0,
            expected_result_set_count=0,
            global_anomaly_codes=("unknown_dynamic_response",),
        )


def test_manifest_rejects_coordinated_response_payload_reseal() -> None:
    records = _response_residual_records(
        payload={"meta": []},
        global_start=0,
        global_anomalies=("unknown_dynamic_response",),
    )
    forged = tuple(
        StatsLosslessRecordV1.from_row(
            _unsafe_reseal_record_row(
                record,
                row_changes={"canonical_payload_sha256": "9" * 64},
                source_changes={"canonical_payload_sha256": "9" * 64},
            )
        )
        for record in records
    )
    with pytest.raises(StatsLosslessValueAuthorityError, match="canonical payload"):
        _build_manifest(
            results=[],
            records=forged,
            provider_result_set_count=0,
            expected_result_set_count=0,
            global_anomaly_codes=("unknown_dynamic_response",),
        )


def test_result_and_manifest_are_value_free_nonrelational_receipts() -> None:
    _records, result, manifest = _authority_rows()
    result_row = result.to_row()
    manifest_row = manifest.to_row()
    assert not any(name.endswith("_json") for name in result_row)
    assert not any(name.endswith("_json") for name in manifest_row)
    assert "raw_headers_json" not in result_row
    assert "raw_rows_json" not in result_row
    assert "global_anomaly_codes_json" not in manifest_row
    assert not hasattr(authority_module, "STATS_LOSSLESS_RESULT_SCHEMA_SHA256")
    assert not hasattr(authority_module, "STATS_LOSSLESS_MANIFEST_SCHEMA_SHA256")


def test_receipt_reconstructs_manifest_and_rejects_exact_type_mutation() -> None:
    _records, _result, manifest = _authority_rows()
    receipt = StatsLosslessValueAuthorityReceiptV1.from_verified_manifest(manifest)
    assert receipt.manifest_sha256 == manifest.manifest_sha256
    assert receipt.raw_authority_bundle_sha256 == _RAW
    assert receipt.route_authority_sha256 == _ROUTE_AUTHORITY
    assert receipt.record_count == manifest.record_count
    assert not any(name.endswith("_json") for name in receipt.identity_payload())

    object.__setattr__(manifest, "manifest_sha256", "0" * 64)
    with pytest.raises(
        StatsLosslessValueAuthorityError,
        match="canonical reconstruction",
    ):
        StatsLosslessValueAuthorityReceiptV1.from_verified_manifest(manifest)


def test_receipt_rejects_poisoned_manifest_field_before_equality() -> None:
    class Poison:
        def __eq__(self, _other: object) -> bool:
            raise AssertionError("poisoned equality ran")

    _records, _result, manifest = _authority_rows()
    object.__setattr__(manifest, "representation_kind", Poison())
    with pytest.raises(
        StatsLosslessValueAuthorityError,
        match="canonical reconstruction",
    ):
        StatsLosslessValueAuthorityReceiptV1.from_verified_manifest(manifest)


def test_manifest_enforces_cross_result_aggregate_byte_bound_before_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records, result, _manifest = _authority_rows()
    total = sum(len(record.canonical_json.encode()) for record in records)
    assert total < MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES
    aggregate_limit = (2 * total) - 1
    assert total < aggregate_limit < 2 * total
    monkeypatch.setattr(
        authority_module,
        "MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES",
        aggregate_limit,
    )
    with pytest.raises(
        StatsLosslessValueAuthorityError,
        match="aggregate canonical byte bound",
    ):
        StatsLosslessManifestV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORD,
            observation_sha256=_OBSERVATION,
            route_id=_ROUTE_ID,
            route_authority_sha256=_ROUTE_AUTHORITY,
            committed_receipt_sha256=_COMMITTED,
            response_receipt_sha256=_RESPONSE,
            endpoint_id=_ENDPOINT,
            endpoint_slug=_ENDPOINT,
            provider_authority_sha256=_PROVIDER,
            endpoint_contract_sha256=_CONTRACT,
            parameters_sha256=_PARAMETERS,
            global_anomaly_codes=_GLOBAL_ANOMALIES,
            provider_result_set_count=1,
            expected_result_set_count=1,
            results=[result, result],
            records=[*records, *records],
        )


@pytest.mark.parametrize(
    "value",
    [
        "Basic Basketball",
        "Bearer of the scoring load",
        "Authorization is required for League Pass",
        "The secret weapon was transition defense",
        "Nikola Jokić — basic basketball excellence",
    ],
)
def test_intrinsic_public_safety_preserves_benign_nba_text(value: str) -> None:
    record = _record(
        global_ordinal=6,
        local_ordinal=6,
        record_kind="cell",
        header_name="A",
        header_ordinal=0,
        row_ordinal=0,
        value=value,
    )
    assert record.value() == value


@pytest.mark.parametrize(
    "value",
    [
        {"nested": [f"ghp_{'A' * 20}"]},
        {"clientSecret": "opaque"},
        {"privateKey": "opaque"},
        {"authToken": "opaque"},
        {"sessionKey": "opaque"},
        {"proxyUrl": "opaque"},
        {"workspacePath": "opaque"},
        ["public", "Authorization: Bearer abcdefghijklmnop1234"],
        ["public", "prefix Authorization: Bearer abcdefghijklmnop1234 suffix"],
        ["public", "prefix Authorization: Basic abcdefghij12 suffix"],
        ["public", "prefix Bearer abcdefghijklmnop1234 suffix"],
        ["public", "prefix Basic abcdefghij12 suffix"],
        ["public", "prefix /Users/private-name suffix"],
        ["public", "prefix /home/private-name suffix"],
        ["public", "prefix /private/var: suffix"],
    ],
)
def test_runtime_and_persisted_rows_reject_nested_secrets_without_echo(value: object) -> None:
    rendered = json.dumps(value, ensure_ascii=False)
    with pytest.raises(StatsLosslessValueAuthorityError, match="secret-shaped") as runtime:
        _record(
            global_ordinal=6,
            local_ordinal=6,
            record_kind="cell",
            header_name="A",
            header_ordinal=0,
            row_ordinal=0,
            value=value,
        )
    assert rendered not in str(runtime.value)

    record = _authority_rows()[0][-1]
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    row = _unsafe_reseal_record_row(
        record,
        row_changes={
            "canonical_json": encoded,
            "canonical_json_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "presence_kind": "present",
            "value_kind": "array" if type(value) is list else "object",
        },
        source_changes={
            "canonical_json": encoded,
            "value_kind": "array" if type(value) is list else "object",
        },
    )
    with pytest.raises(
        StatsLosslessValueAuthorityError,
        match="failed semantic reconstruction",
    ) as persisted:
        StatsLosslessRecordV1.from_row(row)
    assert rendered not in str(persisted.value)


def test_pandera_record_schema_rejects_nested_secrets_and_header_keys_without_echo() -> None:
    records = _authority_rows()[0]
    rows = [record.to_row() for record in records]
    secret = f"ghp_{'Z' * 20}"
    encoded = json.dumps({"nested": [secret]}, sort_keys=True, separators=(",", ":"))
    rows[-1] = _unsafe_reseal_record_row(
        records[-1],
        row_changes={
            "canonical_json": encoded,
            "canonical_json_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "presence_kind": "present",
            "value_kind": "object",
        },
        source_changes={"canonical_json": encoded, "value_kind": "object"},
    )
    with pytest.raises(Exception) as nested:
        RawNbaApiStatsLosslessRecordSchema.validate(pl.DataFrame(rows))
    assert secret not in str(nested.value)

    rows = [record.to_row() for record in records]
    rows[3] = _unsafe_reseal_record_row(
        records[3],
        row_changes={"header_name": "clientSecret"},
        source_changes={"header_name": "clientSecret"},
    )
    with pytest.raises(Exception) as header:
        RawNbaApiStatsLosslessRecordSchema.validate(pl.DataFrame(rows))
    assert "clientSecret" not in str(header.value)


@pytest.mark.parametrize(
    "value",
    [
        ["public", "prefix Authorization: Bearer abcdefghijklmnop1234 suffix"],
        ["public", "prefix Authorization: Basic abcdefghij12 suffix"],
        ["public", "prefix Bearer abcdefghijklmnop1234 suffix"],
        ["public", "prefix Basic abcdefghij12 suffix"],
        ["public", "prefix /Users/private-name suffix"],
        ["public", "prefix /home/private-name suffix"],
        ["public", "prefix /private/var: suffix"],
        {"authToken": "opaque"},
        {"sessionKey": "opaque"},
        {"proxyUrl": "opaque"},
        {"workspacePath": "opaque"},
    ],
)
def test_pandera_record_schema_rejects_contextual_sensitive_values_without_echo(
    value: object,
) -> None:
    records = _authority_rows()[0]
    rows = [record.to_row() for record in records]
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    value_kind = "array" if type(value) is list else "object" if type(value) is dict else "string"
    rows[-1] = _unsafe_reseal_record_row(
        records[-1],
        row_changes={
            "canonical_json": encoded,
            "canonical_json_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "presence_kind": "present",
            "value_kind": value_kind,
        },
        source_changes={"canonical_json": encoded, "value_kind": value_kind},
    )
    with pytest.raises(Exception) as caught:
        RawNbaApiStatsLosslessRecordSchema.validate(pl.DataFrame(rows))
    assert "abcdefghijklmnop1234" not in str(caught.value)
    assert "abcdefghij12" not in str(caught.value)


def test_from_row_rejects_poisoned_schema_version_before_equality() -> None:
    class Poison:
        def __eq__(self, _other: object) -> bool:
            raise AssertionError("poisoned equality ran")

    row = _authority_rows()[0][0].to_row()
    row["schema_version"] = Poison()
    with pytest.raises(StatsLosslessValueAuthorityError, match="schema version"):
        StatsLosslessRecordV1.from_row(row)


def test_builders_reject_foreign_sequences_before_length_or_iteration() -> None:
    class BombList(list[StatsLosslessRecordV1]):
        def __len__(self) -> int:
            raise AssertionError("foreign sequence length was touched")

        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("foreign sequence was iterated")

    records, _result, _manifest = _authority_rows()
    with pytest.raises(StatsLosslessValueAuthorityError, match="exact bounded public sequence"):
        StatsLosslessResultV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORD,
            observation_sha256=_OBSERVATION,
            occurrence_sha256=_OCCURRENCE,
            route_id=_ROUTE_ID,
            route_authority_sha256=_ROUTE_AUTHORITY,
            committed_receipt_sha256=_COMMITTED,
            response_receipt_sha256=_RESPONSE,
            result_ordinal=0,
            result_set_name="Main",
            result_set_occurrence=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            occurrence_canonical_result_ordinal=None,
            presence="present",
            expected_headers=["A"],
            raw_headers=["A"],
            raw_rows=[[1]],
            header_record_count=1,
            raw_row_occurrence_count=1,
            sequence_row_count=1,
            raw_cell_count=1,
            anomaly_codes=["additive_header"],
            normalized_output_sha256="0" * 64,
            first_global_record_ordinal=0,
            records=BombList(records),
        )


def test_canonical_decoder_bounds_depth_and_normalizes_recursion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = "[" * (authority_module.MAX_STATS_LOSSLESS_DEPTH + 1)
    hostile += "0"
    hostile += "]" * (authority_module.MAX_STATS_LOSSLESS_DEPTH + 1)
    with pytest.raises(StatsLosslessValueAuthorityError, match="depth bound"):
        authority_module._decode_canonical_json(hostile)

    def recurse(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("attacker recursion")

    monkeypatch.setattr(authority_module.json, "loads", recurse)
    with pytest.raises(
        StatsLosslessValueAuthorityError,
        match="cannot be decoded",
    ) as exc_info:
        authority_module._decode_canonical_json("[]")
    assert exc_info.value.__cause__ is None
    assert "attacker recursion" not in str(exc_info.value)


def test_record_from_row_and_pandera_callback_normalize_recursion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [record.to_row() for record in _authority_rows()[0]]

    def recurse_decode(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("attacker recursion")

    monkeypatch.setattr(authority_module, "_decode_canonical_json", recurse_decode)
    with pytest.raises(
        StatsLosslessValueAuthorityError,
        match="failed semantic reconstruction",
    ) as exc_info:
        StatsLosslessRecordV1.from_row(rows[0])
    assert exc_info.value.__cause__ is None
    assert "attacker recursion" not in str(exc_info.value)

    monkeypatch.undo()

    def recurse_row(_value: object) -> StatsLosslessRecordV1:
        raise RecursionError("attacker recursion")

    monkeypatch.setattr(
        schema_module.StatsLosslessRecordV1,
        "from_row",
        staticmethod(recurse_row),
    )
    with pytest.raises(Exception) as schema_error:
        RawNbaApiStatsLosslessRecordSchema.validate(pl.DataFrame(rows))
    assert not isinstance(schema_error.value, RecursionError)
    assert "attacker recursion" not in str(schema_error.value)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("presence", "present_empty"),
        ("expected_headers_sha256", "5" * 64),
        ("occurrence_canonical_result_ordinal", 0),
        ("raw_headers_sha256", "6" * 64),
        ("raw_rows_sha256", "7" * 64),
        ("raw_header_container_kind", "object"),
        ("raw_row_container_kind", "object"),
        ("header_record_count", 1),
        ("raw_row_occurrence_count", 0),
        ("sequence_row_count", 0),
        ("raw_cell_count", 1),
        ("anomaly_codes_sha256", "8" * 64),
        ("normalized_output_sha256", "9" * 64),
        ("first_global_record_ordinal", 1),
        ("record_count", 7),
        ("record_inventory_sha256", "0" * 64),
        ("source_rows_sha256", "1" * 64),
    ],
)
def test_manifest_rederives_every_result_commitment_from_records(
    field_name: str,
    replacement: object,
) -> None:
    records, result, _manifest = _authority_rows()
    resealed = StatsLosslessResultV1.from_row(
        _unsafe_reseal_result_row(result, changes={field_name: replacement})
    )
    with pytest.raises(
        StatsLosslessValueAuthorityError,
        match="partition|exact raw containers",
    ):
        _build_manifest(results=[resealed], records=records)


@pytest.mark.parametrize(
    ("provider_count", "expected_count"),
    [(0, 1), (1, 0), (1, 2)],
)
def test_manifest_derives_denominators_instead_of_trusting_callers(
    provider_count: int,
    expected_count: int,
) -> None:
    records, result, _manifest = _authority_rows()
    with pytest.raises(StatsLosslessValueAuthorityError, match="denominator"):
        _build_manifest(
            results=[result],
            records=records,
            provider_result_set_count=provider_count,
            expected_result_set_count=expected_count,
        )


def test_manifest_and_receipt_share_exact_denominator_algebra_under_reseal() -> None:
    _records, _result, manifest = _authority_rows()
    manifest_row = manifest.to_row()
    manifest_row["expected_result_set_count"] = 2
    manifest_payload = {
        "schema_version": manifest_row["schema_version"],
        "kind": StatsLosslessManifestV1.kind,
        **{
            name: value
            for name, value in manifest_row.items()
            if name not in {"schema_version", "manifest_sha256"}
        },
    }
    manifest_row["manifest_sha256"] = _unsafe_canonical_sha256(manifest_payload)
    with pytest.raises(
        StatsLosslessValueAuthorityError,
        match="failed semantic reconstruction",
    ):
        StatsLosslessManifestV1.from_row(manifest_row)

    receipt = StatsLosslessValueAuthorityReceiptV1.from_verified_manifest(manifest)
    receipt_payload = receipt.identity_payload()
    receipt_values = {
        name: value
        for name, value in receipt_payload.items()
        if name not in {"schema_version", "kind"}
    }
    receipt_values["expected_result_set_count"] = 2
    resealed_payload = {
        "schema_version": receipt.schema_version,
        "kind": receipt.kind,
        **receipt_values,
    }
    with pytest.raises(StatsLosslessValueAuthorityError, match="denominator"):
        StatsLosslessValueAuthorityReceiptV1(
            authority_sha256=_unsafe_canonical_sha256(resealed_payload),
            **receipt_values,  # type: ignore[arg-type]
        )


def test_all_additive_results_cannot_create_an_empty_expected_denominator() -> None:
    raw_headers = ["A", "B"]
    raw_rows = [[1, 2]]
    output_sha256 = canonical_sha256({"headers": raw_headers, "rows": raw_rows, "anomalies": []})
    declaration = stats_lossless_result_declaration_value(
        presence="present",
        expected_headers=None,
        anomaly_codes=(),
        normalized_output_sha256=output_sha256,
        header_record_count=2,
        raw_row_occurrence_count=1,
        sequence_row_count=1,
        raw_cell_count=2,
    )
    values = (
        ("result_set", None, None, None, declaration),
        ("raw_headers", None, None, None, raw_headers),
        ("raw_rows", None, None, None, raw_rows),
        ("header", "A", 0, None, "A"),
        ("header", "B", 1, None, "B"),
        ("row", None, None, 0, [1, 2]),
        ("cell", "A", 0, 0, 1),
        ("cell", "B", 1, 0, 2),
    )
    records = tuple(
        StatsLosslessRecordV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORD,
            observation_sha256=_OBSERVATION,
            owner_kind="result_occurrence",
            occurrence_sha256=_OCCURRENCE,
            route_id=_ROUTE_ID,
            route_authority_sha256=_ROUTE_AUTHORITY,
            committed_receipt_sha256=_COMMITTED,
            response_receipt_sha256=_RESPONSE,
            provider_authority_sha256=_PROVIDER,
            endpoint_contract_sha256=_CONTRACT,
            response_mode_authority_sha256=_RESPONSE_MODE,
            parser_input_sha256=_PARSER_INPUT,
            canonical_payload_sha256=_CANONICAL_PAYLOAD,
            parameters_sha256=_PARAMETERS,
            endpoint_id=_ENDPOINT,
            endpoint_slug=_ENDPOINT,
            response_state="legacy_present_nonempty",
            legacy_envelope_name="resultSets",
            global_record_ordinal=ordinal,
            occurrence_record_ordinal=ordinal,
            response_record_ordinal=None,
            record_kind=kind,  # type: ignore[arg-type]
            result_set_name="Extra",
            result_set_occurrence=0,
            provider_result_ordinal=0,
            expected_result_ordinal=None,
            canonical_result_ordinal=None,
            header_name=header_name,
            header_ordinal=header_ordinal,
            row_ordinal=row_ordinal,
            value_present=True,
            value=value,
            global_anomaly_codes=("additive_result_set",),
        )
        for ordinal, (kind, header_name, header_ordinal, row_ordinal, value) in enumerate(values)
    )
    result = StatsLosslessResultV1.build(
        raw_authority_bundle_sha256=_RAW,
        observation_record_sha256=_OBSERVATION_RECORD,
        observation_sha256=_OBSERVATION,
        occurrence_sha256=_OCCURRENCE,
        route_id=_ROUTE_ID,
        route_authority_sha256=_ROUTE_AUTHORITY,
        committed_receipt_sha256=_COMMITTED,
        response_receipt_sha256=_RESPONSE,
        result_ordinal=0,
        result_set_name="Extra",
        result_set_occurrence=0,
        provider_result_ordinal=0,
        expected_result_ordinal=None,
        canonical_result_ordinal=None,
        occurrence_canonical_result_ordinal=None,
        presence="present",
        expected_headers=None,
        raw_headers=raw_headers,
        raw_rows=raw_rows,
        header_record_count=2,
        raw_row_occurrence_count=1,
        sequence_row_count=1,
        raw_cell_count=2,
        anomaly_codes=(),
        normalized_output_sha256=output_sha256,
        first_global_record_ordinal=0,
        records=records,
    )
    with pytest.raises(StatsLosslessValueAuthorityError, match="expected-result denominator"):
        _build_manifest(
            results=[result],
            records=records,
            expected_result_set_count=0,
            global_anomaly_codes=("additive_result_set",),
        )
