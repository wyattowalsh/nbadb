from __future__ import annotations

import ast
import hashlib
import inspect
import json
from copy import deepcopy
from typing import Any

import pytest

from nbadb.contracts import independent_stats_lossless_table_verifier as verifier_module
from nbadb.contracts import stats_lossless_value_authority as authority_module
from nbadb.contracts.independent_stats_lossless_table_verifier import (
    CONDITIONAL_ROUTE_PUBLIC_COLUMNS,
    RAW_RESULT_OCCURRENCE_V2_COLUMNS,
    IndependentStatsLosslessTableVerifierError,
    verify_stats_lossless_public_tables,
)
from nbadb.contracts.raw_request_authority import ResultOccurrenceV2
from nbadb.contracts.stats_lossless_value_authority import (
    STATS_LOSSLESS_RECORD_COLUMNS,
    StatsLosslessManifestV1,
    StatsLosslessRecordV1,
    StatsLosslessResultV1,
    StatsLosslessValueAuthorityReceiptV1,
    canonical_json_bytes,
    canonical_ordered_root_sha256,
    canonical_sha256,
    stats_lossless_result_declaration_value,
)

_RAW = "a" * 64
_RAW_SECOND = "0" * 64
_OBSERVATION_RECORD = "b" * 64
_OBSERVATION = "c" * 64
_COMMITTED = "d" * 64
_RESPONSE = "e" * 64
_PROVIDER = "f" * 64
_CONTRACT = "1" * 64
_PARAMETERS = "2" * 64
_READBACK = "3" * 64
_BODY = "4" * 64
_PARENT_STATE = "5" * 64
_RESPONSE_MODE = "6" * 64
_PARSER_INPUT = "7" * 64
_CANONICAL_PAYLOAD = "8" * 64
_ENDPOINT = "example"
_ROUTE_ID = f"{_ENDPOINT}:stg_nba_api_lossless_result_cells:2"
_PLACEHOLDER_ROUTE = "9" * 64
_NO_RESIDUAL = object()


def _canonical_text(value: object) -> str:
    return canonical_json_bytes(value, maximum_bytes=64 * 1024 * 1024).decode("utf-8")


def _raw_occurrence(
    *,
    occurrence_ordinal: int,
    result_name: str,
    duplicate_name_ordinal: int,
    provider_result_ordinal: int | None,
    presence: str,
    ordered_headers: tuple[str, ...],
    row_count: int,
    output_sha256: str,
    landing_disposition: str,
) -> dict[str, object]:
    headers_json = _canonical_text(list(ordered_headers))
    headers_sha256 = hashlib.sha256(headers_json.encode()).hexdigest()
    route_ids_json = _canonical_text([_ROUTE_ID])
    route_ids_sha256 = hashlib.sha256(route_ids_json.encode()).hexdigest()
    receipts_json = _canonical_text([{"receipt_sha256": _COMMITTED, "route_id": _ROUTE_ID}])
    receipts_sha256 = hashlib.sha256(receipts_json.encode()).hexdigest()
    missing_count = 1 if presence == "missing" else 0
    container_count = 0 if presence == "missing" else 1
    logical_payload = {
        "schema_version": 2,
        "observation_sha256": _OBSERVATION,
        "occurrence_ordinal": occurrence_ordinal,
        "result_name": result_name,
        "duplicate_name_ordinal": duplicate_name_ordinal,
        "provider_result_ordinal": provider_result_ordinal,
        "canonical_result_ordinal": None,
        "json_path": None,
        "container_kind": "nba_api_result_set",
        "presence": presence,
        "ordered_headers_sha256": headers_sha256,
        "header_count": len(ordered_headers),
        "row_count": row_count,
        "cell_count": len(ordered_headers) * row_count,
        "node_count": 0,
        "container_count": container_count,
        "missing_count": missing_count,
        "null_count": 0,
        "parent_state_sha256": _PARENT_STATE,
        "output_sha256": output_sha256,
    }
    logical_receipt = canonical_sha256(logical_payload)
    route_receipt = canonical_sha256(
        {
            "logical_result_receipt_sha256": logical_receipt,
            "canonical_route_ids_sha256": route_ids_sha256,
            "landing_disposition": landing_disposition,
        }
    )
    occurrence_payload = {
        **logical_payload,
        "ordered_headers_json": headers_json,
        "canonical_route_ids_json": route_ids_json,
        "canonical_route_ids_sha256": route_ids_sha256,
        "committed_staging_receipts_json": receipts_json,
        "committed_staging_receipts_sha256": receipts_sha256,
        "landing_disposition": landing_disposition,
        "logical_result_receipt_sha256": logical_receipt,
        "route_receipt_sha256": route_receipt,
    }
    return {
        "schema_version": 2,
        "occurrence_sha256": canonical_sha256(occurrence_payload),
        "observation_sha256": _OBSERVATION,
        "occurrence_ordinal": occurrence_ordinal,
        "result_name": result_name,
        "duplicate_name_ordinal": duplicate_name_ordinal,
        "provider_result_ordinal": provider_result_ordinal,
        "canonical_result_ordinal": None,
        "json_path": None,
        "container_kind": "nba_api_result_set",
        "presence": presence,
        "ordered_headers_json": headers_json,
        "ordered_headers_sha256": headers_sha256,
        "header_count": len(ordered_headers),
        "row_count": row_count,
        "cell_count": len(ordered_headers) * row_count,
        "node_count": 0,
        "container_count": container_count,
        "missing_count": missing_count,
        "null_count": 0,
        "parent_state_sha256": _PARENT_STATE,
        "output_sha256": output_sha256,
        "canonical_route_ids_json": route_ids_json,
        "canonical_route_ids_sha256": route_ids_sha256,
        "committed_staging_receipts_json": receipts_json,
        "committed_staging_receipts_sha256": receipts_sha256,
        "landing_disposition": landing_disposition,
        "logical_result_receipt_sha256": logical_receipt,
        "route_receipt_sha256": route_receipt,
    }


def _binding(
    *,
    ordinal: int,
    source: dict[str, object],
    occurrence_sha256: str | None,
) -> dict[str, object]:
    binding_kind = "selected_result_bound" if occurrence_sha256 is not None else "body_node_bound"
    row_identity_json = _canonical_text(source)
    selectors = sorted(key for key, value in source.items() if value is not None)
    values: dict[str, object] = {
        "binding_id": (f"conditional_lossless_binding:{_ROUTE_ID}:{ordinal:08d}:{binding_kind}"),
        "binding_kind": binding_kind,
        "route_id": _ROUTE_ID,
        "staging_key": "stg_nba_api_lossless_result_cells",
        "staging_row_ordinal": ordinal,
        "observation_record_sha256": _OBSERVATION_RECORD,
        "observation_sha256": _OBSERVATION,
        "source_occurrence_sha256": occurrence_sha256,
        "body_object_sha256": None if occurrence_sha256 is not None else _BODY,
        "response_receipt_sha256": source["response_receipt_sha256"],
        "record_kind": source["record_kind"],
        "result_set_name": source["result_set_name"],
        "result_set_occurrence": source["result_set_occurrence"],
        "provider_index": source["provider_index"],
        "canonical_index": source["canonical_index"],
        "header_name": source["header_name"],
        "header_ordinal": source["header_ordinal"],
        "row_ordinal": source["row_ordinal"],
        "node_ordinal": source["node_ordinal"],
        "parent_node_ordinal": source["parent_node_ordinal"],
        "json_path": source["json_path"],
        "parent_json_path": source["parent_json_path"],
        "depth": source["depth"],
        "object_key": source["object_key"],
        "object_key_ordinal": source["object_key_ordinal"],
        "array_ordinal": source["array_ordinal"],
        "selector_columns": selectors,
        "row_identity_json": row_identity_json,
        "row_identity_sha256": canonical_sha256(source),
    }
    return {**values, "binding_evidence_sha256": canonical_sha256(values)}


def _route_authority(
    occurrences: list[dict[str, object]],
    sources: list[dict[str, object]],
    occurrence_for_source: list[str | None],
    *,
    raw_authority_bundle_sha256: str,
) -> dict[str, object]:
    bindings = [
        _binding(ordinal=ordinal, source=source, occurrence_sha256=occurrence_for_source[ordinal])
        for ordinal, source in enumerate(sources)
    ]
    bindings.sort(key=lambda value: str(value["binding_id"]))
    has_occurrences = bool(occurrences)
    has_body = any(item is None for item in occurrence_for_source)
    source_shape = (
        "hybrid_result_body_bound"
        if has_occurrences and has_body
        else ("body_node_bound" if has_body else "selected_result_bound")
    )
    identity = {
        "schema_version": 1,
        "kind": "conditional_route_occurrence_authority",
        "route_id": _ROUTE_ID,
        "route_local_ordinal": 0,
        "endpoint_name": _ENDPOINT,
        "source_family": "stats",
        "source_shape": source_shape,
        "staging_key": "stg_nba_api_lossless_result_cells",
        "schema_tier": "staging",
        "schema_table": "stg_nba_api_lossless_result_cells",
        "schema_class": "RawNbaApiLosslessFallbackSchema",
        "storage_role": "conditional_lossless",
        "route_admission_sha256": "6" * 64,
        "field_fate_structure_sha256": "7" * 64,
        "provider_authority_sha256": _PROVIDER,
        "endpoint_contract_sha256": _CONTRACT,
        "committed_logical_parameters_sha256": _PARAMETERS,
        "source_parameters_sha256s": [_PARAMETERS],
        "staging_parameters_sha256": None,
        "raw_bundle_sha256": raw_authority_bundle_sha256,
        "readback_receipt_sha256": _READBACK,
        "committed_receipt_root_sha256": _COMMITTED,
        "response_receipt_sha256": _RESPONSE,
        "observation_record_sha256s": [_OBSERVATION_RECORD],
        "result_occurrence_sha256s": sorted(str(item["occurrence_sha256"]) for item in occurrences),
        "body_object_sha256s": [_BODY] if has_body else [],
        "stats_bindings": bindings,
        "live_binding_ids": [],
        "sinks": [{"sink_id": "sink"}],
    }
    return {**identity, "authority_sha256": canonical_sha256(identity)}


def _specs(
    *,
    unsupported_containers: bool,
    normal_wide: bool,
    additive_only: bool,
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], list[dict[str, object]], tuple[str, ...]]:
    expected: tuple[tuple[str, tuple[str, ...]], ...]
    provider: list[dict[str, object]]
    global_anomalies: tuple[str, ...]
    if additive_only:
        expected = ()
        provider = [
            {
                "name": "Extra",
                "expected_ordinal": None,
                "raw_headers": [],
                "raw_rows": [[]],
                "anomalies": (),
                "landing": "wide_plus_lossless",
            }
        ]
        global_anomalies = ("additive_result_set",)
    elif unsupported_containers:
        expected = (("Main", ("A",)),)
        provider = [
            {
                "name": "Main",
                "expected_ordinal": 0,
                "raw_headers": {"unexpected": 1},
                "raw_rows": {"unexpected": 2},
                "anomalies": (
                    "removed_header",
                    "unsupported_header_shape",
                    "unsupported_row_container",
                ),
                "landing": "lossless_only",
            }
        ]
        global_anomalies = (
            "removed_header",
            "unsupported_header_shape",
            "unsupported_row_container",
        )
    elif normal_wide:
        expected = (("Main", ("A",)),)
        provider = [
            {
                "name": "Main",
                "expected_ordinal": 0,
                "raw_headers": ["A"],
                "raw_rows": [[1]],
                "anomalies": (),
                "landing": "wide_plus_lossless",
            }
        ]
        global_anomalies = ("unrepresentable_typed_frame",)
    else:
        expected = (("Base", ("A", "B")), ("Missing", ("M",)))
        provider = [
            {
                "name": "Base",
                "expected_ordinal": 0,
                "raw_headers": ["A", "A", "C"],
                "raw_rows": [[1, "x"], [2.5, {"k": "v"}, 3], {"raw": True}],
                "anomalies": (
                    "additive_header",
                    "duplicate_header",
                    "heterogeneous_column",
                    "non_sequence_row",
                    "ragged_row",
                    "removed_header",
                ),
                "landing": "lossless_only",
            },
            {
                "name": "Base",
                "expected_ordinal": 0,
                "raw_headers": ["A", "B"],
                "raw_rows": [],
                "anomalies": (),
                "landing": "lossless_only",
            },
            {
                "name": "Extra",
                "expected_ordinal": None,
                "raw_headers": [],
                "raw_rows": [[]],
                "anomalies": (),
                "landing": "wide_plus_lossless",
            },
        ]
        global_anomalies = tuple(
            sorted(
                {
                    "additive_header",
                    "additive_result_set",
                    "duplicate_header",
                    "duplicate_result_set_name",
                    "heterogeneous_column",
                    "missing_result_set",
                    "non_sequence_row",
                    "ragged_row",
                    "removed_header",
                }
            )
        )
    return expected, provider, global_anomalies


def _declared_bundle(
    *,
    raw_authority_bundle_sha256: str = _RAW,
    unsupported_containers: bool = False,
    normal_wide: bool = False,
    additive_only: bool = False,
    injected_cell_value: object | None = None,
    response_residual: object = _NO_RESIDUAL,
    residual_only: bool = False,
) -> dict[str, Any]:
    if residual_only:
        expected: tuple[tuple[str, tuple[str, ...]], ...] = ()
        provider_specs: list[dict[str, object]] = []
        global_anomalies = ("unknown_dynamic_response",)
    else:
        expected, provider_specs, global_anomalies = _specs(
            unsupported_containers=unsupported_containers,
            normal_wide=normal_wide,
            additive_only=additive_only,
        )
        if response_residual is not _NO_RESIDUAL:
            global_anomalies = tuple(
                sorted(
                    {
                        *(
                            ()
                            if global_anomalies == ("unrepresentable_typed_frame",)
                            else global_anomalies
                        ),
                        "unknown_dynamic_response",
                    }
                )
            )
    if injected_cell_value is not None:
        raw_rows = provider_specs[0]["raw_rows"]
        if type(raw_rows) is not list or not raw_rows or type(raw_rows[0]) is not list:
            raise AssertionError("injected verifier fixture lacks one exact sequence cell")
        raw_rows[0][0] = injected_cell_value
    canonical_payload_sha256 = (
        _CANONICAL_PAYLOAD
        if response_residual is _NO_RESIDUAL
        else canonical_sha256(response_residual)
    )
    response_state = (
        "legacy_present_nonempty"
        if response_residual is _NO_RESIDUAL
        else "unknown_result_envelope"
    )
    legacy_envelope_name = "resultSets" if response_residual is _NO_RESIDUAL else None
    provider_counts: dict[str, int] = {}
    for spec in provider_specs:
        name = str(spec["name"])
        provider_counts[name] = provider_counts.get(name, 0) + 1
    specs: list[dict[str, object]] = []
    duplicate_counts: dict[str, int] = {}
    for provider_ordinal, spec in enumerate(provider_specs):
        name = str(spec["name"])
        duplicate_ordinal = duplicate_counts.get(name, 0)
        duplicate_counts[name] = duplicate_ordinal + 1
        expected_ordinal = spec["expected_ordinal"]
        expected_headers = None if expected_ordinal is None else expected[int(expected_ordinal)][1]
        raw_headers = spec["raw_headers"]
        raw_rows = spec["raw_rows"]
        anomalies = tuple(spec["anomalies"])
        output = canonical_sha256(
            {"headers": raw_headers, "rows": raw_rows, "anomalies": list(anomalies)}
        )
        header_names = (
            tuple(raw_headers)
            if isinstance(raw_headers, list) and all(isinstance(item, str) for item in raw_headers)
            else ()
        )
        ordered_headers = (
            tuple(str(item) for item in header_names)
            if all(bool(item) for item in header_names)
            else ()
        )
        row_count = len(raw_rows) if isinstance(raw_rows, list) else 0
        specs.append(
            {
                "name": name,
                "duplicate_ordinal": duplicate_ordinal,
                "provider_ordinal": provider_ordinal,
                "expected_ordinal": expected_ordinal,
                "canonical_ordinal": (expected_ordinal if provider_counts[name] == 1 else None),
                "expected_headers": expected_headers,
                "raw_headers": raw_headers,
                "raw_rows": raw_rows,
                "anomalies": anomalies,
                "output": output,
                "ordered_headers": ordered_headers,
                "presence": "present" if row_count else "present_empty",
                "row_count": row_count,
                "landing": spec["landing"],
            }
        )
    for expected_ordinal, (name, expected_headers) in enumerate(expected):
        if provider_counts.get(name, 0):
            continue
        specs.append(
            {
                "name": name,
                "duplicate_ordinal": 0,
                "provider_ordinal": None,
                "expected_ordinal": expected_ordinal,
                "canonical_ordinal": expected_ordinal,
                "expected_headers": expected_headers,
                "raw_headers": list(expected_headers),
                "raw_rows": [],
                "anomalies": (),
                "output": canonical_sha256({"headers": list(expected_headers), "rows": []}),
                "ordered_headers": (),
                "presence": "missing",
                "row_count": 0,
                "landing": "lossless_only",
            }
        )

    occurrences = [
        _raw_occurrence(
            occurrence_ordinal=ordinal,
            result_name=str(spec["name"]),
            duplicate_name_ordinal=int(spec["duplicate_ordinal"]),
            provider_result_ordinal=(
                None if spec["provider_ordinal"] is None else int(spec["provider_ordinal"])
            ),
            presence=str(spec["presence"]),
            ordered_headers=tuple(spec["ordered_headers"]),
            row_count=int(spec["row_count"]),
            output_sha256=str(spec["output"]),
            landing_disposition=str(spec["landing"]),
        )
        for ordinal, spec in enumerate(specs)
    ]

    def build_records(
        route_authority_sha256: str,
    ) -> tuple[
        list[StatsLosslessRecordV1],
        list[list[StatsLosslessRecordV1]],
    ]:
        all_records: list[StatsLosslessRecordV1] = []
        partitions: list[list[StatsLosslessRecordV1]] = []
        for spec, occurrence in zip(specs, occurrences, strict=True):
            partition: list[StatsLosslessRecordV1] = []
            provider_ordinal = (
                None if spec["provider_ordinal"] is None else int(spec["provider_ordinal"])
            )
            expected_ordinal = (
                None if spec["expected_ordinal"] is None else int(spec["expected_ordinal"])
            )
            canonical_ordinal = (
                None if spec["canonical_ordinal"] is None else int(spec["canonical_ordinal"])
            )
            raw_headers = spec["raw_headers"]
            raw_rows = spec["raw_rows"]
            header_values = tuple(raw_headers) if isinstance(raw_headers, list) else ()
            header_names = tuple(item if isinstance(item, str) else None for item in header_values)
            row_values = raw_rows if isinstance(raw_rows, list) else []
            sequence_rows = [row for row in row_values if isinstance(row, list)]
            declaration = stats_lossless_result_declaration_value(
                presence=str(spec["presence"]),  # type: ignore[arg-type]
                expected_headers=(
                    None if spec["expected_headers"] is None else tuple(spec["expected_headers"])
                ),
                anomaly_codes=tuple(spec["anomalies"]),
                normalized_output_sha256=str(spec["output"]),
                header_record_count=(0 if provider_ordinal is None else len(header_values)),
                raw_row_occurrence_count=(0 if provider_ordinal is None else len(row_values)),
                sequence_row_count=(0 if provider_ordinal is None else len(sequence_rows)),
                raw_cell_count=(
                    0 if provider_ordinal is None else sum(len(row) for row in sequence_rows)
                ),
            )
            record_values: list[tuple[str, str | None, int | None, int | None, object]] = [
                (
                    "missing_expected" if provider_ordinal is None else "result_set",
                    None,
                    None,
                    None,
                    declaration,
                ),
                ("raw_headers", None, None, None, raw_headers),
                ("raw_rows", None, None, None, raw_rows),
            ]
            if provider_ordinal is not None:
                for header_ordinal, header_value in enumerate(header_values):
                    record_values.append(
                        (
                            "header",
                            header_names[header_ordinal],
                            header_ordinal,
                            None,
                            header_value,
                        )
                    )
                for row_ordinal, raw_row in enumerate(row_values):
                    record_values.append(("row", None, None, row_ordinal, raw_row))
                    if isinstance(raw_row, list):
                        for header_ordinal, cell in enumerate(raw_row):
                            record_values.append(
                                (
                                    "cell",
                                    (
                                        header_names[header_ordinal]
                                        if header_ordinal < len(header_names)
                                        else None
                                    ),
                                    header_ordinal,
                                    row_ordinal,
                                    cell,
                                )
                            )
            for local_ordinal, (
                kind,
                header_name,
                header_ordinal,
                row_ordinal,
                value,
            ) in enumerate(record_values):
                record = StatsLosslessRecordV1.build(
                    raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                    observation_record_sha256=_OBSERVATION_RECORD,
                    observation_sha256=_OBSERVATION,
                    owner_kind="result_occurrence",
                    occurrence_sha256=str(occurrence["occurrence_sha256"]),
                    route_id=_ROUTE_ID,
                    route_authority_sha256=route_authority_sha256,
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
                    global_record_ordinal=len(all_records),
                    occurrence_record_ordinal=local_ordinal,
                    response_record_ordinal=None,
                    record_kind=kind,  # type: ignore[arg-type]
                    result_set_name=str(spec["name"]),
                    result_set_occurrence=int(spec["duplicate_ordinal"]),
                    provider_result_ordinal=provider_ordinal,
                    expected_result_ordinal=expected_ordinal,
                    canonical_result_ordinal=canonical_ordinal,
                    header_name=header_name,
                    header_ordinal=header_ordinal,
                    row_ordinal=row_ordinal,
                    value_present=True,
                    value=value,
                    global_anomaly_codes=global_anomalies,
                )
                all_records.append(record)
                partition.append(record)
            partitions.append(partition)
        if response_residual is not _NO_RESIDUAL:
            response_marker = StatsLosslessRecordV1.build(
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                observation_record_sha256=_OBSERVATION_RECORD,
                observation_sha256=_OBSERVATION,
                owner_kind="response_residual",
                occurrence_sha256=None,
                route_id=_ROUTE_ID,
                route_authority_sha256=route_authority_sha256,
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
                legacy_envelope_name=None,
                global_record_ordinal=len(all_records),
                occurrence_record_ordinal=None,
                response_record_ordinal=0,
                record_kind="response",
                result_set_name=None,
                result_set_occurrence=None,
                provider_result_ordinal=None,
                expected_result_ordinal=None,
                canonical_result_ordinal=None,
                global_anomaly_codes=global_anomalies,
            )
            all_records.append(response_marker)

            node_specs: list[dict[str, object]] = []

            def visit_node(
                value: object,
                *,
                parent_node_ordinal: int | None,
                tokens: tuple[str | int, ...],
                object_key: str | None,
                object_key_ordinal: int | None,
                array_ordinal: int | None,
            ) -> None:
                node_ordinal = len(node_specs)
                parent_tokens = tokens[:-1]
                node_specs.append(
                    {
                        "value": value,
                        "node_ordinal": node_ordinal,
                        "parent_node_ordinal": parent_node_ordinal,
                        "json_path": (
                            "$"
                            + "".join(
                                f"[{token}]"
                                if type(token) is int
                                else f"[{_canonical_text(token)}]"
                                for token in tokens
                            )
                        ),
                        "parent_json_path": (
                            None
                            if parent_node_ordinal is None
                            else "$"
                            + "".join(
                                f"[{token}]"
                                if type(token) is int
                                else f"[{_canonical_text(token)}]"
                                for token in parent_tokens
                            )
                        ),
                        "depth": len(tokens),
                        "object_key": object_key,
                        "object_key_ordinal": object_key_ordinal,
                        "array_ordinal": array_ordinal,
                    }
                )
                if type(value) is dict:
                    for ordinal, (key, child) in enumerate(value.items()):
                        visit_node(
                            child,
                            parent_node_ordinal=node_ordinal,
                            tokens=(*tokens, key),
                            object_key=key,
                            object_key_ordinal=ordinal,
                            array_ordinal=None,
                        )
                elif type(value) is list:
                    for ordinal, child in enumerate(value):
                        visit_node(
                            child,
                            parent_node_ordinal=node_ordinal,
                            tokens=(*tokens, ordinal),
                            object_key=None,
                            object_key_ordinal=None,
                            array_ordinal=ordinal,
                        )

            visit_node(
                response_residual,
                parent_node_ordinal=None,
                tokens=(),
                object_key=None,
                object_key_ordinal=None,
                array_ordinal=None,
            )
            for response_ordinal, spec in enumerate(node_specs, start=1):
                value = spec["value"]
                nonempty_container = type(value) in {dict, list} and bool(value)
                all_records.append(
                    StatsLosslessRecordV1.build(
                        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                        observation_record_sha256=_OBSERVATION_RECORD,
                        observation_sha256=_OBSERVATION,
                        owner_kind="response_residual",
                        occurrence_sha256=None,
                        route_id=_ROUTE_ID,
                        route_authority_sha256=route_authority_sha256,
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
                        legacy_envelope_name=None,
                        global_record_ordinal=len(all_records),
                        occurrence_record_ordinal=None,
                        response_record_ordinal=response_ordinal,
                        record_kind="json_node",
                        result_set_name=None,
                        result_set_occurrence=None,
                        provider_result_ordinal=None,
                        expected_result_ordinal=None,
                        canonical_result_ordinal=None,
                        node_ordinal=int(spec["node_ordinal"]),
                        parent_node_ordinal=(
                            None
                            if spec["parent_node_ordinal"] is None
                            else int(spec["parent_node_ordinal"])
                        ),
                        json_path=str(spec["json_path"]),
                        parent_json_path=(
                            None
                            if spec["parent_json_path"] is None
                            else str(spec["parent_json_path"])
                        ),
                        depth=int(spec["depth"]),
                        object_key=(
                            None if spec["object_key"] is None else str(spec["object_key"])
                        ),
                        object_key_ordinal=(
                            None
                            if spec["object_key_ordinal"] is None
                            else int(spec["object_key_ordinal"])
                        ),
                        array_ordinal=(
                            None if spec["array_ordinal"] is None else int(spec["array_ordinal"])
                        ),
                        value_present=not nonempty_container,
                        value=value,
                        explicit_presence_kind=("present" if nonempty_container else None),
                        explicit_value_kind=(
                            "object"
                            if type(value) is dict and nonempty_container
                            else ("array" if type(value) is list and nonempty_container else None)
                        ),
                        global_anomaly_codes=global_anomalies,
                    )
                )
        return all_records, partitions

    preliminary, preliminary_partitions = build_records(_PLACEHOLDER_ROUTE)
    preliminary_sources = [record.source_row() for record in preliminary]
    occurrence_for_source: list[str | None] = [
        str(occurrences[result_ordinal]["occurrence_sha256"])
        for result_ordinal, partition in enumerate(preliminary_partitions)
        for _record in partition
    ]
    occurrence_for_source.extend([None] * (len(preliminary) - len(occurrence_for_source)))
    route = _route_authority(
        occurrences,
        preliminary_sources,
        occurrence_for_source,
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
    )
    route_sha = str(route["authority_sha256"])
    records, partitions = build_records(route_sha)
    sources = [record.source_row() for record in records]
    assert sources == preliminary_sources

    results: list[StatsLosslessResultV1] = []
    for result_ordinal, (spec, occurrence, partition) in enumerate(
        zip(specs, occurrences, partitions, strict=True)
    ):
        provider_ordinal = (
            None if spec["provider_ordinal"] is None else int(spec["provider_ordinal"])
        )
        raw_rows = spec["raw_rows"]
        row_values = raw_rows if isinstance(raw_rows, list) else []
        sequence_rows = [row for row in row_values if isinstance(row, list)]
        raw_headers = spec["raw_headers"]
        header_values = tuple(raw_headers) if isinstance(raw_headers, list) else ()
        results.append(
            StatsLosslessResultV1.build(
                raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                observation_record_sha256=_OBSERVATION_RECORD,
                observation_sha256=_OBSERVATION,
                occurrence_sha256=str(occurrence["occurrence_sha256"]),
                route_id=_ROUTE_ID,
                route_authority_sha256=route_sha,
                committed_receipt_sha256=_COMMITTED,
                response_receipt_sha256=_RESPONSE,
                result_ordinal=result_ordinal,
                result_set_name=str(spec["name"]),
                result_set_occurrence=int(spec["duplicate_ordinal"]),
                provider_result_ordinal=provider_ordinal,
                expected_result_ordinal=(
                    None if spec["expected_ordinal"] is None else int(spec["expected_ordinal"])
                ),
                canonical_result_ordinal=(
                    None if spec["canonical_ordinal"] is None else int(spec["canonical_ordinal"])
                ),
                occurrence_canonical_result_ordinal=None,
                presence=str(spec["presence"]),  # type: ignore[arg-type]
                expected_headers=(
                    None if spec["expected_headers"] is None else tuple(spec["expected_headers"])
                ),
                raw_headers=raw_headers,
                raw_rows=raw_rows,
                header_record_count=(0 if provider_ordinal is None else len(header_values)),
                raw_row_occurrence_count=(0 if provider_ordinal is None else len(row_values)),
                sequence_row_count=(0 if provider_ordinal is None else len(sequence_rows)),
                raw_cell_count=(
                    0 if provider_ordinal is None else sum(len(row) for row in sequence_rows)
                ),
                anomaly_codes=tuple(spec["anomalies"]),
                normalized_output_sha256=str(spec["output"]),
                first_global_record_ordinal=partition[0].global_record_ordinal,
                records=partition,
            )
        )
    expected_receipt: StatsLosslessValueAuthorityReceiptV1 | None = None
    if expected or response_residual is not _NO_RESIDUAL:
        manifest = StatsLosslessManifestV1.build(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            observation_record_sha256=_OBSERVATION_RECORD,
            observation_sha256=_OBSERVATION,
            route_id=_ROUTE_ID,
            route_authority_sha256=route_sha,
            committed_receipt_sha256=_COMMITTED,
            response_receipt_sha256=_RESPONSE,
            endpoint_id=_ENDPOINT,
            endpoint_slug=_ENDPOINT,
            provider_authority_sha256=_PROVIDER,
            endpoint_contract_sha256=_CONTRACT,
            parameters_sha256=_PARAMETERS,
            global_anomaly_codes=global_anomalies,
            provider_result_set_count=len(provider_specs),
            expected_result_set_count=len(expected),
            results=results,
            records=records,
        )
        expected_receipt = StatsLosslessValueAuthorityReceiptV1.from_verified_manifest(manifest)
    return {
        "expected_raw_authority_bundle_sha256": raw_authority_bundle_sha256,
        "expected_route_authority_sha256": route_sha,
        "route_authority_row": route,
        "occurrence_rows": occurrences,
        "source_rows": sources,
        "record_rows": [record.to_row() for record in records],
        "expected_receipt": expected_receipt,
        "global_anomalies": global_anomalies,
    }


def _verify(bundle: dict[str, Any]):
    return verify_stats_lossless_public_tables(
        expected_raw_authority_bundle_sha256=bundle["expected_raw_authority_bundle_sha256"],
        expected_route_authority_sha256=bundle["expected_route_authority_sha256"],
        route_authority_row=bundle["route_authority_row"],
        occurrence_rows=bundle["occurrence_rows"],
        source_rows=bundle["source_rows"],
        record_rows=bundle["record_rows"],
    )


def _coordinated_reseal_residual_record(
    bundle: dict[str, Any],
    *,
    record_index: int,
    row_changes: dict[str, object],
    source_changes: dict[str, object],
) -> None:
    row = bundle["record_rows"][record_index]
    source = bundle["source_rows"][record_index]
    row.update(row_changes)
    source.update(source_changes)
    row["source_row_sha256"] = canonical_sha256(source)

    route = bundle["route_authority_row"]
    binding = next(
        item for item in route["stats_bindings"] if item["staging_row_ordinal"] == record_index
    )
    for binding_name, source_name in (
        ("response_receipt_sha256", "response_receipt_sha256"),
        ("record_kind", "record_kind"),
        ("result_set_name", "result_set_name"),
        ("result_set_occurrence", "result_set_occurrence"),
        ("provider_index", "provider_index"),
        ("canonical_index", "canonical_index"),
        ("header_name", "header_name"),
        ("header_ordinal", "header_ordinal"),
        ("row_ordinal", "row_ordinal"),
        ("node_ordinal", "node_ordinal"),
        ("parent_node_ordinal", "parent_node_ordinal"),
        ("json_path", "json_path"),
        ("parent_json_path", "parent_json_path"),
        ("depth", "depth"),
        ("object_key", "object_key"),
        ("object_key_ordinal", "object_key_ordinal"),
        ("array_ordinal", "array_ordinal"),
    ):
        binding[binding_name] = source[source_name]
    binding["selector_columns"] = sorted(key for key, value in source.items() if value is not None)
    binding["row_identity_json"] = _canonical_text(source)
    binding["row_identity_sha256"] = canonical_sha256(source)
    binding["binding_evidence_sha256"] = canonical_sha256(
        {key: value for key, value in binding.items() if key != "binding_evidence_sha256"}
    )
    route["authority_sha256"] = canonical_sha256(
        {key: value for key, value in route.items() if key != "authority_sha256"}
    )
    bundle["expected_route_authority_sha256"] = route["authority_sha256"]
    for record in bundle["record_rows"]:
        record["route_authority_sha256"] = route["authority_sha256"]
        record["record_sha256"] = canonical_sha256(
            {
                "schema_version": record["schema_version"],
                "kind": StatsLosslessRecordV1.kind,
                **{
                    column: record[column]
                    for column in STATS_LOSSLESS_RECORD_COLUMNS[1:]
                    if column != "record_sha256"
                },
            }
        )


def test_single_public_relation_closes_all_lossless_drift_and_matches_builder() -> None:
    bundle = _declared_bundle()
    receipt = _verify(bundle)
    assert receipt == bundle["expected_receipt"]
    assert receipt.result_count == 4
    assert receipt.record_count == len(bundle["record_rows"])
    assert bundle["global_anomalies"] == tuple(
        sorted(
            {
                "additive_header",
                "additive_result_set",
                "duplicate_header",
                "duplicate_result_set_name",
                "heterogeneous_column",
                "missing_result_set",
                "non_sequence_row",
                "ragged_row",
                "removed_header",
            }
        )
    )


def test_independent_verifier_closes_distinct_bundle_local_zero_scopes() -> None:
    first = _declared_bundle(raw_authority_bundle_sha256=_RAW)
    second = _declared_bundle(raw_authority_bundle_sha256=_RAW_SECOND)
    first_receipt = _verify(first)
    second_receipt = _verify(second)

    assert first["record_rows"][0]["global_record_ordinal"] == 0
    assert second["record_rows"][0]["global_record_ordinal"] == 0
    assert first_receipt.raw_authority_bundle_sha256 == _RAW
    assert second_receipt.raw_authority_bundle_sha256 == _RAW_SECOND
    assert first_receipt.authority_sha256 != second_receipt.authority_sha256
    assert first_receipt == first["expected_receipt"]
    assert second_receipt == second["expected_receipt"]


def test_independent_verifier_rejects_cross_bundle_valid_row_substitution() -> None:
    admitted = _declared_bundle(raw_authority_bundle_sha256=_RAW)
    foreign = _declared_bundle(raw_authority_bundle_sha256=_RAW_SECOND)
    admitted["source_rows"][0] = foreign["source_rows"][0]
    admitted["record_rows"][0] = foreign["record_rows"][0]

    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="bundle|provenance|source",
    ):
        _verify(admitted)


def test_zero_response_residual_partition_has_an_explicit_empty_root() -> None:
    receipt = _verify(_declared_bundle())
    assert receipt.response_residual_record_count == 0
    assert receipt.response_residual_records_sha256 == canonical_ordered_root_sha256(
        kind="stats_lossless_response_residual_records_v1",
        count=0,
        values=(),
    )


def test_hybrid_occurrence_and_response_residual_closes_exact_body_tree() -> None:
    payload = {
        "flags": [True, None],
        "meta": {"season": "2025-26"},
    }
    bundle = _declared_bundle(normal_wide=True, response_residual=payload)
    receipt = _verify(bundle)
    assert receipt == bundle["expected_receipt"]
    assert receipt.result_count == 1
    assert receipt.expected_result_set_count == 1
    assert receipt.response_residual_record_count == 7
    assert bundle["route_authority_row"]["source_shape"] == "hybrid_result_body_bound"
    assert {item["binding_kind"] for item in bundle["route_authority_row"]["stats_bindings"]} == {
        "selected_result_bound",
        "body_node_bound",
    }
    residual_rows = [
        row for row in bundle["record_rows"] if row["owner_kind"] == "response_residual"
    ]
    assert residual_rows[0]["record_kind"] == "response"
    assert all(row["occurrence_sha256"] is None for row in residual_rows)
    assert [row["response_record_ordinal"] for row in residual_rows] == list(
        range(len(residual_rows))
    )


def test_response_residual_only_closes_zero_result_denominators() -> None:
    bundle = _declared_bundle(response_residual={"meta": []}, residual_only=True)
    receipt = _verify(bundle)
    assert receipt == bundle["expected_receipt"]
    assert receipt.provider_result_set_count == 0
    assert receipt.expected_result_set_count == 0
    assert receipt.occurrence_count == 0
    assert receipt.result_count == 0
    assert receipt.response_residual_record_count == 3
    assert bundle["route_authority_row"]["source_shape"] == "body_node_bound"
    assert bundle["route_authority_row"]["result_occurrence_sha256s"] == []


@pytest.mark.parametrize(
    ("row_offset", "row_changes", "source_changes"),
    [
        (0, {"response_record_ordinal": 1}, {}),
        (1, {"node_ordinal": 1}, {"node_ordinal": 1}),
        (2, {"json_path": '$["forged"]'}, {"json_path": '$["forged"]'}),
        (
            0,
            {"canonical_payload_sha256": "0" * 64},
            {"canonical_payload_sha256": "0" * 64},
        ),
    ],
)
def test_coordinated_residual_reseals_cannot_change_partition_or_tree_semantics(
    row_offset: int,
    row_changes: dict[str, object],
    source_changes: dict[str, object],
) -> None:
    bundle = _declared_bundle(
        normal_wide=True,
        response_residual={"meta": {"season": "2025-26"}},
    )
    residual_start = next(
        index
        for index, row in enumerate(bundle["record_rows"])
        if row["owner_kind"] == "response_residual"
    )
    _coordinated_reseal_residual_record(
        bundle,
        record_index=residual_start + row_offset,
        row_changes=row_changes,
        source_changes=source_changes,
    )
    with pytest.raises(IndependentStatsLosslessTableVerifierError):
        _verify(bundle)


def test_unsupported_raw_containers_live_in_record_rows_not_result_sidecars() -> None:
    bundle = _declared_bundle(unsupported_containers=True)
    receipt = _verify(bundle)
    values = {
        row["record_kind"]: json.loads(str(row["canonical_json"]))
        for row in bundle["record_rows"][:3]
    }
    assert receipt.result_count == 1
    assert values["raw_headers"] == {"unexpected": 1}
    assert values["raw_rows"] == {"unexpected": 2}


def test_genuine_raw_v2_additive_result_wide_plus_lossless_is_admitted() -> None:
    bundle = _declared_bundle()
    additive_index = next(
        index
        for index, row in enumerate(bundle["occurrence_rows"])
        if row["result_name"] == "Extra"
    )
    genuine = ResultOccurrenceV2(**bundle["occurrence_rows"][additive_index])
    assert genuine.landing_disposition == "wide_plus_lossless"
    bundle["occurrence_rows"][additive_index] = genuine.to_row()
    assert _verify(bundle).result_count == 4


def test_wide_plus_lossless_without_reconstructed_drift_fails_closed() -> None:
    bundle = _declared_bundle(normal_wide=True)
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="lacks reconstructed lossless drift",
    ):
        _verify(bundle)


@pytest.mark.parametrize("target", ["source_rows", "record_rows", "occurrence_rows"])
def test_public_relation_or_authority_drops_fail_closed(target: str) -> None:
    bundle = _declared_bundle()
    bundle[target] = bundle[target][:-1]
    with pytest.raises(IndependentStatsLosslessTableVerifierError):
        _verify(bundle)


def test_addition_reordering_binding_and_source_rebinding_fail_closed() -> None:
    added = _declared_bundle()
    added["record_rows"].append(deepcopy(added["record_rows"][-1]))
    with pytest.raises(IndependentStatsLosslessTableVerifierError):
        _verify(added)

    reordered = _declared_bundle()
    reordered["record_rows"][0], reordered["record_rows"][1] = (
        reordered["record_rows"][1],
        reordered["record_rows"][0],
    )
    with pytest.raises(IndependentStatsLosslessTableVerifierError):
        _verify(reordered)

    rebound = _declared_bundle()
    rebound["source_rows"][4]["canonical_json"] = "999"
    with pytest.raises(IndependentStatsLosslessTableVerifierError):
        _verify(rebound)

    binding = _declared_bundle()
    binding["route_authority_row"]["stats_bindings"][0]["row_identity_sha256"] = "8" * 64
    with pytest.raises(IndependentStatsLosslessTableVerifierError):
        _verify(binding)


def test_coordinated_resealing_cannot_cross_the_admitted_route_root() -> None:
    original = _declared_bundle()
    resealed = _declared_bundle(unsupported_containers=True)
    resealed["expected_route_authority_sha256"] = original["expected_route_authority_sha256"]
    with pytest.raises(IndependentStatsLosslessTableVerifierError, match="admitted root"):
        _verify(resealed)


def test_persisted_rows_receive_nested_secret_gate_without_echo() -> None:
    bundle = _declared_bundle()
    secret = f"ghp_{'Z' * 20}"
    bundle["source_rows"][4]["canonical_json"] = json.dumps(
        {"nested": [secret]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="secret-shaped",
    ) as exc_info:
        _verify(bundle)
    assert secret not in str(exc_info.value)


def test_independent_canonical_decoder_rejects_secret_before_other_closure_checks() -> None:
    secret = f"ghp_{'Y' * 20}"
    encoded = json.dumps(
        {"nested": [secret]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="secret-shaped",
    ) as exc_info:
        verifier_module._canonical_value(encoded, label="hostile public row")
    assert secret not in str(exc_info.value)


@pytest.mark.parametrize(
    "value",
    [
        "prefix Authorization: Bearer abcdefghijklmnop1234 suffix",
        "prefix Authorization: Basic abcdefghij12 suffix",
        "prefix Bearer abcdefghijklmnop1234 suffix",
        "prefix Basic abcdefghij12 suffix",
        "prefix /Users/private-name suffix",
        "prefix /home/private-name suffix",
        "prefix /private/var: suffix",
        {"authToken": "opaque"},
        {"sessionKey": "opaque"},
        {"proxyUrl": "opaque"},
        {"workspacePath": "opaque"},
    ],
)
def test_sensitive_values_fail_independent_decoder_and_top_level_verifier(
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="secret-shaped",
    ) as decoded:
        verifier_module._canonical_value(encoded, label="contextual secret")
    assert encoded not in str(decoded.value)

    with monkeypatch.context() as bypass:
        bypass.setattr(authority_module, "_reject_secret_shaped_public_text", lambda _value: None)
        bypass.setattr(authority_module, "_reject_sensitive_public_key", lambda _value: None)
        bundle = _declared_bundle(injected_cell_value=value)
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="secret-shaped",
    ) as verified:
        _verify(bundle)
    assert encoded not in str(verified.value)


def test_independent_canonical_decoder_bounds_depth_and_normalizes_recursion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = "[" * (verifier_module._MAX_STATS_LOSSLESS_DEPTH + 1)
    hostile += "0"
    hostile += "]" * (verifier_module._MAX_STATS_LOSSLESS_DEPTH + 1)
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="depth bound",
    ):
        verifier_module._canonical_value(hostile, label="hostile public row")

    def recurse(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("attacker recursion")

    monkeypatch.setattr(verifier_module.json, "loads", recurse)
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="cannot be decoded",
    ) as exc_info:
        verifier_module._canonical_value("[]", label="hostile public row")
    assert exc_info.value.__cause__ is None
    assert "attacker recursion" not in str(exc_info.value)


def test_complete_independent_verifier_normalizes_recursion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def recurse(**_kwargs: object) -> StatsLosslessValueAuthorityReceiptV1:
        raise RecursionError("attacker recursion")

    monkeypatch.setattr(verifier_module, "_verify_stats_lossless_public_tables", recurse)
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="recursion bound",
    ) as exc_info:
        verify_stats_lossless_public_tables(
            expected_raw_authority_bundle_sha256=_RAW,
            expected_route_authority_sha256=_PLACEHOLDER_ROUTE,
            route_authority_row={},
            occurrence_rows=[],
            source_rows=[],
            record_rows=[],
        )
    assert exc_info.value.__cause__ is None
    assert "attacker recursion" not in str(exc_info.value)


def test_independent_verifier_rejects_all_additive_empty_expected_denominator() -> None:
    bundle = _declared_bundle(additive_only=True)
    assert bundle["expected_receipt"] is None
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="expected-result denominator",
    ):
        _verify(bundle)


@pytest.mark.parametrize("target", ["route_authority_row", "occurrence_rows", "record_rows"])
def test_poisoned_schema_version_fails_before_attacker_equality(
    target: str,
) -> None:
    class Poison:
        def __eq__(self, _other: object) -> bool:
            raise AssertionError("attacker equality ran")

    bundle = _declared_bundle()
    if target == "route_authority_row":
        bundle[target]["schema_version"] = Poison()
    else:
        bundle[target][0]["schema_version"] = Poison()
    with pytest.raises(IndependentStatsLosslessTableVerifierError):
        _verify(bundle)


def test_poisoned_mapping_key_fails_before_attacker_hash_or_equality() -> None:
    calls = 0

    class PoisonKey:
        def __hash__(self) -> int:
            nonlocal calls
            calls += 1
            return 7

        def __eq__(self, _other: object) -> bool:
            raise AssertionError("attacker key equality ran")

    bundle = _declared_bundle()
    key = PoisonKey()
    hostile = {key: 1, **bundle["record_rows"][0]}
    calls = 0
    bundle["record_rows"][0] = hostile
    with pytest.raises(IndependentStatsLosslessTableVerifierError, match="ordered public columns"):
        _verify(bundle)
    assert calls == 0


def test_foreign_sequences_fail_before_length_or_iteration() -> None:
    class BombList(list[object]):
        def __len__(self) -> int:
            raise AssertionError("foreign sequence length was touched")

        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("foreign sequence was iterated")

    bundle = _declared_bundle()
    bundle["source_rows"] = BombList(bundle["source_rows"])
    with pytest.raises(
        IndependentStatsLosslessTableVerifierError,
        match="exact structured row sequence",
    ):
        _verify(bundle)


def test_route_and_occurrence_rows_require_exact_frozen_column_order() -> None:
    bundle = _declared_bundle()
    assert tuple(bundle["route_authority_row"]) == CONDITIONAL_ROUTE_PUBLIC_COLUMNS
    assert tuple(bundle["occurrence_rows"][0]) == RAW_RESULT_OCCURRENCE_V2_COLUMNS
    bundle["route_authority_row"] = {
        key: bundle["route_authority_row"][key] for key in reversed(bundle["route_authority_row"])
    }
    with pytest.raises(IndependentStatsLosslessTableVerifierError, match="ordered public columns"):
        _verify(bundle)


def test_verifier_import_call_graph_and_signature_are_independent_and_table_only() -> None:
    source = inspect.getsource(verifier_module)
    tree = ast.parse(source)
    forbidden_modules = {
        "nba_api_adapter",
        "raw_request_authority",
        "field_fate_structure",
        "stats_lossless",
        "staging_map",
        "schema_registry",
        "polars",
        "pandera",
    }
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
    assert not any(
        forbidden in imported.split(".")
        for imported in imported_modules
        for forbidden in forbidden_modules
    )
    signature = inspect.signature(verify_stats_lossless_public_tables)
    assert "result_rows" not in signature.parameters
    assert "manifest_row" not in signature.parameters
    authority_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == (
            "nbadb.contracts.stats_lossless_value_authority"
        ):
            authority_imports.update(alias.name for alias in node.names)
    assert authority_imports == {
        "MAX_STATS_LOSSLESS_CANONICAL_BYTES",
        "MAX_STATS_LOSSLESS_CELLS",
        "MAX_STATS_LOSSLESS_HEADERS",
        "MAX_STATS_LOSSLESS_RECORDS",
        "MAX_STATS_LOSSLESS_RESULTS",
        "MAX_STATS_LOSSLESS_ROWS",
        "MAX_STATS_LOSSLESS_TOTAL_CANONICAL_BYTES",
        "PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION",
        "RESPONSE_LOSSLESS_REPRESENTATION_KIND",
        "STATS_LOSSLESS_RECORD_COLUMNS",
        "STATS_LOSSLESS_RECORD_SCHEMA_SHA256",
        "STATS_LOSSLESS_REPRESENTATION_KIND",
        "STATS_LOSSLESS_SOURCE_COLUMNS",
        "STATS_LOSSLESS_SOURCE_SCHEMA_SHA256",
        "StatsLosslessValueAuthorityReceiptV1",
    }
    forbidden_calls = {"build", "from_row", "from_verified_manifest", "validate"}
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in forbidden_calls
        for node in ast.walk(tree)
    )
