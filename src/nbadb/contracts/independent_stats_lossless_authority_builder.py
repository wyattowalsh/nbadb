"""Independent Raw-V2 to stats-lossless public-authority adapter.

The adapter consumes only the exact public parser-input objects already sealed
inside Raw Request Authority V2.  It never imports or observes the production
NBA parser, extraction frames, staging tables, or public-table rows.  Every
response is decoded by :mod:`independent_stats_projection_decoder`, joined
back to its Raw-V2 occurrence and conditional-route identities, and then
rebuilt through the canonical stats-lossless public DTO constructors.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import TYPE_CHECKING, Final, Never, TypedDict, cast

from nbadb.contracts.independent_stats_projection_decoder import (
    DecodedStatsProjectionResponseV1,
    DecodedStatsProjectionResultV1,
    decode_stats_projection_response,
    validate_decoded_stats_projection_response,
)
from nbadb.contracts.raw_request_authority import (
    MAX_AUTHORITY_ROWS,
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    decode_parser_input_object,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_request_observation_order import canonical_raw_request_observations
from nbadb.contracts.stats_lossless_value_authority import (
    MAX_STATS_LOSSLESS_RECORDS,
    MAX_STATS_LOSSLESS_RESULTS,
    JsonPresenceKind,
    JsonValueKind,
    StatsLosslessRecordKind,
    StatsLosslessRecordV1,
    StatsLosslessResultPresence,
    StatsLosslessResultV1,
    StatsLosslessValueAuthorityV1,
    build_stats_lossless_value_authority,
    stats_lossless_result_declaration_value,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "IndependentStatsLosslessAuthorityBuilderError",
    "build_independent_stats_lossless_authorities",
]


_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_LOSSLESS_DISPOSITIONS: Final = frozenset({"lossless_only", "wide_plus_lossless"})
_UNKNOWN_RESPONSE_PINS: Final[Mapping[str, tuple[str, str]]] = {
    "VideoDetails": ("documented_empty_result_inventory", "package_exported"),
    "VideoDetailsAsset": ("documented_empty_result_inventory", "package_exported"),
    "VideoEvents": ("documented_empty_result_inventory", "package_exported"),
    "VideoEventsAsset": ("endpoint_doc_absent", "direct_import_only"),
}


class _RecordCommon(TypedDict):
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    route_id: str
    route_authority_sha256: str
    committed_receipt_sha256: str
    response_receipt_sha256: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    response_mode_authority_sha256: str
    parser_input_sha256: str
    canonical_payload_sha256: str
    parameters_sha256: str
    endpoint_id: str
    endpoint_slug: str
    response_state: str
    legacy_envelope_name: str | None
    global_anomaly_codes: tuple[str, ...]


class IndependentStatsLosslessAuthorityBuilderError(ValueError):
    """Exact Raw-V2 bytes cannot close one stats-lossless authority."""


def _fail(message: str) -> Never:
    raise IndependentStatsLosslessAuthorityBuilderError(message) from None


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _canonical_sha256(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError, MemoryError):
        _fail("stats-lossless response-mode authority cannot be encoded")
    return hashlib.sha256(encoded).hexdigest()


def _decode_canonical_json(value: object, *, label: str) -> object:
    if type(value) is not str:
        _fail(f"{label} is not exact canonical JSON text")
    raw = value
    try:
        decoded = json.loads(
            raw,
            parse_constant=lambda _item: (_ for _ in ()).throw(ValueError()),
        )
        rebuilt = json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (
        TypeError,
        ValueError,
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        RecursionError,
        MemoryError,
    ):
        _fail(f"{label} failed exact canonical reconstruction")
    if rebuilt != raw:
        _fail(f"{label} is not canonical JSON")
    return decoded


def _preflight_raw_bundle(value: RawRequestAuthorityBundleV2) -> None:
    if (
        type(value.objects) is not tuple
        or len(value.objects) > MAX_AUTHORITY_ROWS
        or any(type(item) is not ParserInputObjectV2 for item in value.objects)
        or type(value.observations) is not tuple
        or len(value.observations) > MAX_AUTHORITY_ROWS
        or any(
            type(item) is not RequestObservationV2
            or type(item.attempt) is not RequestAttemptIdentityV2
            for item in value.observations
        )
        or type(value.occurrences) is not tuple
        or len(value.occurrences) > MAX_AUTHORITY_ROWS
        or any(type(item) is not ResultOccurrenceV2 for item in value.occurrences)
        or type(value.landings) is not tuple
        or len(value.landings) > MAX_AUTHORITY_ROWS
        or any(type(item) is not ObservationRouteLandingV2 for item in value.landings)
    ):
        _fail("Raw Authority V2 contains a foreign or over-bound child inventory")


def _response_mode_authority_sha256(
    response: DecodedStatsProjectionResponseV1,
) -> str:
    """Reproduce the closed response-mode authority without runtime imports."""

    if response.response_mode == "declared_result_sets":
        if response.endpoint_id in _UNKNOWN_RESPONSE_PINS or response.expected_result_set_count < 1:
            _fail("declared stats response differs from the closed response-mode policy")
        provider_result_inventory = "named_result_sets"
        observed_packet_mode = "declared_result_sets_only"
        endpoint_doc_status = None
        package_export_status = None
    elif response.response_mode == "unknown_dynamic_response":
        statuses = _UNKNOWN_RESPONSE_PINS.get(response.endpoint_id)
        if statuses is None or response.expected_result_set_count != 0:
            _fail("unknown stats response differs from the exact four-endpoint policy")
        provider_result_inventory = "endpoint_expected_data_empty_unknown"
        observed_packet_mode = "fail_closed_json_object_or_legacy_result_sets"
        endpoint_doc_status, package_export_status = statuses
    else:  # pragma: no cover - projection DTO closes this discriminator
        _fail("stats response has a foreign response mode")
    return _canonical_sha256(
        {
            "runtime_class_name": response.endpoint_id,
            "module_name": f"nba_api.stats.endpoints.{response.endpoint_slug}",
            "endpoint_slug": response.endpoint_slug,
            "response_mode": response.response_mode,
            "provider_result_inventory": provider_result_inventory,
            "observed_packet_mode": observed_packet_mode,
            "endpoint_doc_status": endpoint_doc_status,
            "package_export_status": package_export_status,
            "endpoint_contract_sha256": response.endpoint_contract_sha256,
        }
    )


def _response_state(
    response: DecodedStatsProjectionResponseV1,
) -> tuple[str, str | None]:
    nodes = response.residual_nodes
    if not nodes or nodes[0].node_ordinal != 0 or nodes[0].value_kind != "object":
        _fail("stats projection residual inventory lacks one response object root")
    root_children = tuple(item for item in nodes[1:] if item.parent_node_ordinal == 0)
    roots = tuple(
        item.object_key for item in root_children if item.object_key in {"resultSets", "resultSet"}
    )
    if len(roots) > 1:
        _fail("stats response has ambiguous legacy result envelopes")
    if roots:
        return (
            "legacy_present_nonempty"
            if any(
                item.provider_result_ordinal is not None and item.raw_row_occurrence_count > 0
                for item in response.results
            )
            else "legacy_present_empty",
            roots[0],
        )
    if not root_children:
        return "missing_result_envelope", None
    if any(item.value_kind in {"array", "object"} for item in root_children):
        return "generic_nested_json", None
    return "unknown_result_envelope", None


def _group_observation_children(
    bundle: RawRequestAuthorityBundleV2,
) -> tuple[
    dict[str, tuple[ResultOccurrenceV2, ...]],
    dict[str, tuple[ObservationRouteLandingV2, ...]],
]:
    """Index every Raw child once in exact observation-local ordinal order."""

    occurrence_slots: dict[str, list[ResultOccurrenceV2 | None]] = {}
    landing_slots: dict[str, list[ObservationRouteLandingV2 | None]] = {}
    for observation in bundle.observations:
        observation_sha256 = observation.attempt.observation_sha256
        if observation_sha256 in occurrence_slots:
            _fail("stats Raw observation inventory repeats one identity")
        occurrence_slots[observation_sha256] = [None] * observation.result_occurrence_count
        landing_slots[observation_sha256] = [None] * observation.route_landing_count
    for occurrence in bundle.occurrences:
        slots = occurrence_slots.get(occurrence.observation_sha256)
        if (
            slots is None
            or occurrence.occurrence_ordinal >= len(slots)
            or slots[occurrence.occurrence_ordinal] is not None
        ):
            _fail("stats Raw occurrence order is sparse, duplicated, or foreign")
        slots[occurrence.occurrence_ordinal] = occurrence
    for landing in bundle.landings:
        slots = landing_slots.get(landing.observation_sha256)
        if (
            slots is None
            or landing.route_ordinal >= len(slots)
            or slots[landing.route_ordinal] is not None
        ):
            _fail("stats Raw landing order is sparse, duplicated, or foreign")
        slots[landing.route_ordinal] = landing

    occurrences_by_observation: dict[str, tuple[ResultOccurrenceV2, ...]] = {}
    landings_by_observation: dict[str, tuple[ObservationRouteLandingV2, ...]] = {}
    for observation in bundle.observations:
        observation_sha256 = observation.attempt.observation_sha256
        raw_occurrences = occurrence_slots[observation_sha256]
        raw_landings = landing_slots[observation_sha256]
        if any(item is None for item in raw_occurrences) or any(
            item is None for item in raw_landings
        ):
            _fail("stats Raw child order is sparse within one observation")
        occurrences_by_observation[observation_sha256] = tuple(
            cast("list[ResultOccurrenceV2]", raw_occurrences)
        )
        landings_by_observation[observation_sha256] = tuple(
            cast("list[ObservationRouteLandingV2]", raw_landings)
        )
    return occurrences_by_observation, landings_by_observation


def _match_raw_occurrences(
    *,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    conditional_landing: ObservationRouteLandingV2,
    response: DecodedStatsProjectionResponseV1,
) -> tuple[tuple[ResultOccurrenceV2, DecodedStatsProjectionResultV1], ...]:
    if len(occurrences) != len(response.results) or len(occurrences) > MAX_STATS_LOSSLESS_RESULTS:
        _fail("stats Raw occurrence denominator differs from independent body decoding")
    matched: list[tuple[ResultOccurrenceV2, DecodedStatsProjectionResultV1]] = []
    for occurrence, result in zip(occurrences, response.results, strict=True):
        if (
            occurrence.observation_sha256 != observation.attempt.observation_sha256
            or occurrence.occurrence_ordinal != result.result_ordinal
            or occurrence.result_name != result.result_name
            or occurrence.duplicate_name_ordinal != result.result_duplicate_ordinal
            or occurrence.provider_result_ordinal != result.provider_result_ordinal
            or (
                occurrence.canonical_result_ordinal is not None
                and occurrence.canonical_result_ordinal != result.canonical_result_ordinal
            )
            or occurrence.container_kind != "nba_api_result_set"
            or occurrence.json_path is not None
            or occurrence.presence != result.presence
            or occurrence.row_count != result.raw_row_occurrence_count
            or occurrence.output_sha256 != result.normalized_output_sha256
            or occurrence.landing_disposition not in _LOSSLESS_DISPOSITIONS
            or conditional_landing.route_id not in occurrence.canonical_route_ids()
        ):
            _fail("stats Raw occurrence differs from independent parser-input decoding")
        matched.append((occurrence, result))
    if conditional_landing.source_occurrence_count != len(occurrences):
        _fail("stats conditional landing occurrence denominator differs from Raw V2")
    return tuple(matched)


def _record_common(
    *,
    bundle: RawRequestAuthorityBundleV2,
    observation: RequestObservationV2,
    landing: ObservationRouteLandingV2,
    response: DecodedStatsProjectionResponseV1,
    response_mode_authority_sha256: str,
    response_state: str,
    legacy_envelope_name: str | None,
    global_anomalies: tuple[str, ...],
) -> _RecordCommon:
    capture_receipt = observation.capture_response_receipt_sha256
    if capture_receipt is None:
        _fail("stats selected observation lacks an exact capture receipt")
    return _RecordCommon(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        observation_record_sha256=observation.observation_record_sha256,
        observation_sha256=observation.attempt.observation_sha256,
        route_id=landing.route_id,
        route_authority_sha256=landing.route_authority_sha256,
        committed_receipt_sha256=landing.receipt_root_sha256,
        response_receipt_sha256=capture_receipt,
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
        endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
        response_mode_authority_sha256=response_mode_authority_sha256,
        parser_input_sha256=response.parser_input_sha256,
        canonical_payload_sha256=response.canonical_payload_sha256,
        parameters_sha256=observation.attempt.safe_parameters_sha256,
        endpoint_id=response.endpoint_id,
        endpoint_slug=response.endpoint_slug,
        response_state=response_state,
        legacy_envelope_name=legacy_envelope_name,
        global_anomaly_codes=global_anomalies,
    )


def _result_records(
    *,
    common: _RecordCommon,
    occurrence: ResultOccurrenceV2,
    result: DecodedStatsProjectionResultV1,
    global_start: int,
) -> tuple[StatsLosslessRecordV1, ...]:
    declaration = _target_result_declaration(result)
    decoded_records = result.records[:3] if result.presence == "missing" else result.records
    rows: list[StatsLosslessRecordV1] = []
    for local_ordinal, decoded in enumerate(decoded_records):
        if decoded.result_record_ordinal != local_ordinal:
            _fail("stats decoded result-record order is noncanonical")
        value = (
            declaration
            if local_ordinal == 0
            else _decode_canonical_json(
                decoded.canonical_json,
                label="stats decoded result record",
            )
        )
        rows.append(
            StatsLosslessRecordV1.build(
                **common,
                owner_kind="result_occurrence",
                occurrence_sha256=occurrence.occurrence_sha256,
                global_record_ordinal=global_start + local_ordinal,
                occurrence_record_ordinal=local_ordinal,
                response_record_ordinal=None,
                record_kind=cast("StatsLosslessRecordKind", decoded.record_kind),
                result_set_name=decoded.result_name,
                result_set_occurrence=decoded.result_duplicate_ordinal,
                provider_result_ordinal=decoded.provider_result_ordinal,
                expected_result_ordinal=decoded.expected_result_ordinal,
                canonical_result_ordinal=decoded.canonical_result_ordinal,
                header_name=decoded.header_name,
                header_ordinal=decoded.header_ordinal,
                row_ordinal=decoded.row_ordinal,
                value_present=True,
                value=value,
            )
        )
    return tuple(rows)


def _target_result_declaration(
    decoded: DecodedStatsProjectionResultV1,
) -> dict[str, object]:
    value = _decode_canonical_json(
        decoded.records[0].canonical_json,
        label="stats decoded result declaration",
    )
    if type(value) is not dict:
        _fail("stats decoded result declaration is not one exact object")
    declaration = cast("dict[str, object]", value)
    expected_headers = declaration.get("expected_headers")
    if expected_headers is not None and (
        type(expected_headers) is not list
        or any(type(item) is not str for item in cast("list[object]", expected_headers))
    ):
        _fail("stats decoded result declaration values are invalid")
    raw_headers = _decode_canonical_json(
        decoded.raw_headers_json,
        label="stats decoded raw headers",
    )
    raw_rows = _decode_canonical_json(
        decoded.raw_rows_json,
        label="stats decoded raw rows",
    )
    if decoded.presence == "missing":
        anomalies: tuple[str, ...] = ()
        normalized_output_sha256 = _canonical_sha256({"headers": expected_headers, "rows": []})
    else:
        reasons: set[str] = set()
        header_values = cast("list[object]", raw_headers) if type(raw_headers) is list else []
        observed_names = tuple(item if type(item) is str else None for item in header_values)
        if type(raw_headers) is not list or any(item is None for item in observed_names):
            reasons.add("unsupported_header_shape")
        observed_headers = tuple(item for item in observed_names if item is not None)
        if len(set(observed_headers)) != len(observed_headers):
            reasons.add("duplicate_header")
        if expected_headers is not None:
            expected_tuple = tuple(cast("list[str]", expected_headers))
            expected_counter = Counter(expected_tuple)
            observed_counter = Counter(observed_headers)
            if observed_counter - expected_counter:
                reasons.add("additive_header")
            if expected_counter - observed_counter:
                reasons.add("removed_header")
            if expected_counter == observed_counter and expected_tuple != observed_headers:
                reasons.add("reordered_header")
        if type(raw_rows) is not list:
            reasons.add("unsupported_row_container")
        else:
            widths: set[int] = set()
            kinds_by_ordinal: dict[int, set[str]] = {}
            for raw_row in cast("list[object]", raw_rows):
                if type(raw_row) is not list:
                    reasons.add("non_sequence_row")
                    continue
                row = cast("list[object]", raw_row)
                widths.add(len(row))
                if len(row) != len(observed_names):
                    reasons.add("ragged_row")
                for ordinal, cell in enumerate(row):
                    kind = (
                        "null"
                        if cell is None
                        else "boolean"
                        if type(cell) is bool
                        else "integer"
                        if type(cell) is int
                        else "number"
                        if type(cell) is float
                        else "string"
                        if type(cell) is str
                        else "array"
                        if type(cell) is list
                        else "object"
                        if type(cell) is dict
                        else "foreign"
                    )
                    if kind != "null":
                        kinds_by_ordinal.setdefault(ordinal, set()).add(kind)
            if len(widths) > 1:
                reasons.add("ragged_row")
            if any(len(kinds) > 1 for kinds in kinds_by_ordinal.values()):
                reasons.add("heterogeneous_column")
        anomalies = tuple(sorted(reasons))
        normalized_output_sha256 = _canonical_sha256(
            {
                "headers": raw_headers,
                "rows": raw_rows,
                "anomalies": list(anomalies),
            }
        )
    return stats_lossless_result_declaration_value(
        presence=cast("StatsLosslessResultPresence", decoded.presence),
        expected_headers=(
            None if expected_headers is None else cast("list[str]", expected_headers)
        ),
        anomaly_codes=anomalies,
        normalized_output_sha256=normalized_output_sha256,
        header_record_count=(0 if decoded.presence == "missing" else decoded.header_record_count),
        raw_row_occurrence_count=decoded.raw_row_occurrence_count,
        sequence_row_count=decoded.sequence_row_count,
        raw_cell_count=decoded.cell_count,
    )


def _result_authority(
    *,
    bundle: RawRequestAuthorityBundleV2,
    observation: RequestObservationV2,
    landing: ObservationRouteLandingV2,
    occurrence: ResultOccurrenceV2,
    decoded: DecodedStatsProjectionResultV1,
    records: tuple[StatsLosslessRecordV1, ...],
    global_start: int,
) -> StatsLosslessResultV1:
    declared = _target_result_declaration(decoded)
    expected_headers = declared.get("expected_headers")
    if expected_headers is not None and (
        type(expected_headers) is not list
        or any(type(item) is not str for item in cast("list[object]", expected_headers))
    ):
        _fail("stats decoded expected headers are invalid")
    raw_headers = _decode_canonical_json(
        decoded.raw_headers_json,
        label="stats decoded raw headers",
    )
    raw_rows = _decode_canonical_json(
        decoded.raw_rows_json,
        label="stats decoded raw rows",
    )
    anomalies = _decode_canonical_json(
        json.dumps(
            declared["anomaly_codes"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        label="stats target result anomalies",
    )
    if type(anomalies) is not list or any(
        type(item) is not str for item in cast("list[object]", anomalies)
    ):
        _fail("stats decoded result anomalies are invalid")
    capture_receipt = observation.capture_response_receipt_sha256
    if capture_receipt is None:  # pragma: no cover - checked by common metadata
        _fail("stats selected observation lacks an exact capture receipt")
    return StatsLosslessResultV1.build(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        observation_record_sha256=observation.observation_record_sha256,
        observation_sha256=observation.attempt.observation_sha256,
        occurrence_sha256=occurrence.occurrence_sha256,
        route_id=landing.route_id,
        route_authority_sha256=landing.route_authority_sha256,
        committed_receipt_sha256=landing.receipt_root_sha256,
        response_receipt_sha256=capture_receipt,
        result_ordinal=decoded.result_ordinal,
        result_set_name=decoded.result_name,
        result_set_occurrence=decoded.result_duplicate_ordinal,
        provider_result_ordinal=decoded.provider_result_ordinal,
        expected_result_ordinal=decoded.expected_result_ordinal,
        canonical_result_ordinal=decoded.canonical_result_ordinal,
        occurrence_canonical_result_ordinal=None,
        presence=cast("StatsLosslessResultPresence", decoded.presence),
        expected_headers=(
            None if expected_headers is None else cast("list[str]", expected_headers)
        ),
        raw_headers=raw_headers,
        raw_rows=raw_rows,
        header_record_count=cast("int", declared["header_record_count"]),
        raw_row_occurrence_count=cast("int", declared["raw_row_occurrence_count"]),
        sequence_row_count=cast("int", declared["sequence_row_count"]),
        raw_cell_count=cast("int", declared["raw_cell_count"]),
        anomaly_codes=cast("list[str]", anomalies),
        normalized_output_sha256=cast("str", declared["normalized_output_sha256"]),
        first_global_record_ordinal=global_start,
        records=records,
    )


def _residual_records(
    *,
    common: _RecordCommon,
    response: DecodedStatsProjectionResponseV1,
    global_start: int,
) -> tuple[StatsLosslessRecordV1, ...]:
    rows = [
        StatsLosslessRecordV1.build(
            **common,
            owner_kind="response_residual",
            occurrence_sha256=None,
            global_record_ordinal=global_start,
            occurrence_record_ordinal=None,
            response_record_ordinal=0,
            record_kind="response",
            result_set_name=None,
            result_set_occurrence=None,
            provider_result_ordinal=None,
            expected_result_ordinal=None,
            canonical_result_ordinal=None,
        )
    ]
    for response_record_ordinal, node in enumerate(response.residual_nodes, start=1):
        value_present = node.canonical_json is not None
        value = (
            _decode_canonical_json(node.canonical_json, label="stats decoded residual node")
            if value_present
            else None
        )
        rows.append(
            StatsLosslessRecordV1.build(
                **common,
                owner_kind="response_residual",
                occurrence_sha256=None,
                global_record_ordinal=global_start + response_record_ordinal,
                occurrence_record_ordinal=None,
                response_record_ordinal=response_record_ordinal,
                record_kind="json_node",
                result_set_name=None,
                result_set_occurrence=None,
                provider_result_ordinal=None,
                expected_result_ordinal=None,
                canonical_result_ordinal=None,
                node_ordinal=node.node_ordinal,
                parent_node_ordinal=node.parent_node_ordinal,
                json_path=node.json_path,
                parent_json_path=node.parent_json_path,
                depth=node.depth,
                object_key=node.object_key,
                object_key_ordinal=node.object_key_ordinal,
                array_ordinal=node.array_ordinal,
                value_present=value_present,
                value=value,
                explicit_presence_kind=(
                    None if value_present else cast("JsonPresenceKind", node.presence_kind)
                ),
                explicit_value_kind=(
                    None if value_present else cast("JsonValueKind", node.value_kind)
                ),
            )
        )
    if len(rows) != response.residual_record_count:
        _fail("stats response residual denominator differs from its decoded authority")
    return tuple(rows)


def _build_one(
    *,
    bundle: RawRequestAuthorityBundleV2,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
    objects_by_sha: Mapping[str, ParserInputObjectV2],
) -> StatsLosslessValueAuthorityV1:
    conditional = tuple(
        item for item in landings if item.landing_semantic == "conditional_lossless"
    )
    if len(conditional) != 1:
        _fail("stats selected observation lacks one exact conditional-lossless landing")
    landing = conditional[0]
    body_object_sha256 = observation.body_object_sha256
    if (
        observation.body_disposition != "public_parser_input"
        or observation.outcome not in {"success_nonempty", "success_empty"}
        or body_object_sha256 is None
        or observation.capture_response_receipt_sha256 is None
    ):
        _fail("stats selected observation lacks one successful public parser input")
    body = objects_by_sha.get(body_object_sha256)
    if body is None:
        _fail("stats selected observation references a missing parser-input object")
    parser_input = decode_parser_input_object(body)
    response = decode_stats_projection_response(
        parser_input,
        endpoint_id=observation.attempt.endpoint_id,
        endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
    )
    response = validate_decoded_stats_projection_response(
        response,
        parser_input_bytes=parser_input,
    )
    if (
        response.parser_input_sha256 != body.response_sha256
        or response.endpoint_id != observation.attempt.endpoint_id
        or response.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
        or response.provider_authority_sha256 != observation.attempt.provider_authority_sha256
    ):
        _fail("stats decoded response differs from its exact Raw-V2 identities")
    matched = _match_raw_occurrences(
        observation=observation,
        occurrences=occurrences,
        conditional_landing=landing,
        response=response,
    )
    anomalies_value = _decode_canonical_json(
        response.anomaly_codes_json,
        label="stats decoded global anomalies",
    )
    if (
        type(anomalies_value) is not list
        or not anomalies_value
        or any(type(item) is not str for item in cast("list[object]", anomalies_value))
    ):
        _fail("conditional stats response lacks one nonempty global anomaly inventory")
    target_result_anomalies = {
        code
        for _occurrence, decoded in matched
        for code in cast("list[str]", _target_result_declaration(decoded)["anomaly_codes"])
    }
    global_anomalies = tuple(
        sorted({*cast("list[str]", anomalies_value), *target_result_anomalies})
    )
    response_state, legacy_envelope_name = _response_state(response)
    common = _record_common(
        bundle=bundle,
        observation=observation,
        landing=landing,
        response=response,
        response_mode_authority_sha256=_response_mode_authority_sha256(response),
        response_state=response_state,
        legacy_envelope_name=legacy_envelope_name,
        global_anomalies=global_anomalies,
    )
    records: list[StatsLosslessRecordV1] = []
    results: list[StatsLosslessResultV1] = []
    for occurrence, decoded in matched:
        result_records = _result_records(
            common=common,
            occurrence=occurrence,
            result=decoded,
            global_start=len(records),
        )
        results.append(
            _result_authority(
                bundle=bundle,
                observation=observation,
                landing=landing,
                occurrence=occurrence,
                decoded=decoded,
                records=result_records,
                global_start=len(records),
            )
        )
        records.extend(result_records)
    records.extend(
        _residual_records(
            common=common,
            response=response,
            global_start=len(records),
        )
    )
    if len(records) > MAX_STATS_LOSSLESS_RECORDS:
        _fail("stats-lossless public record inventory exceeds its exact bound")
    capture_receipt = observation.capture_response_receipt_sha256
    if capture_receipt is None:  # pragma: no cover - checked above
        _fail("stats selected observation lacks an exact capture receipt")
    return build_stats_lossless_value_authority(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        observation_record_sha256=observation.observation_record_sha256,
        observation_sha256=observation.attempt.observation_sha256,
        route_id=landing.route_id,
        route_authority_sha256=landing.route_authority_sha256,
        committed_receipt_sha256=landing.receipt_root_sha256,
        response_receipt_sha256=capture_receipt,
        endpoint_id=response.endpoint_id,
        endpoint_slug=response.endpoint_slug,
        provider_authority_sha256=response.provider_authority_sha256,
        endpoint_contract_sha256=response.endpoint_contract_sha256,
        parameters_sha256=observation.attempt.safe_parameters_sha256,
        global_anomaly_codes=global_anomalies,
        provider_result_set_count=sum(item.provider_result_ordinal is not None for item in results),
        expected_result_set_count=len(
            {
                item.expected_result_ordinal
                for item in results
                if item.expected_result_ordinal is not None
            }
        ),
        results=results,
        records=records,
    )


def build_independent_stats_lossless_authorities(
    raw_bundle: object,
    *,
    expected_raw_authority_bundle_sha256: str,
) -> tuple[StatsLosslessValueAuthorityV1, ...]:
    """Build every conditional stats authority in canonical observation order."""

    expected_pin = _exact_sha256(
        expected_raw_authority_bundle_sha256,
        label="expected Raw Authority V2 bundle",
    )
    if type(raw_bundle) is not RawRequestAuthorityBundleV2:
        _fail("stats-lossless source must be exact Raw Authority V2")
    if (
        _exact_sha256(
            raw_bundle.bundle_sha256,
            label="Raw Authority V2 bundle identity",
        )
        != expected_pin
    ):
        _fail("stats-lossless source differs from its external bundle pin")
    try:
        _preflight_raw_bundle(raw_bundle)
        bundle = validate_raw_request_authority_bundle(raw_bundle)
        if type(bundle) is not RawRequestAuthorityBundleV2 or bundle.bundle_sha256 != expected_pin:
            _fail("stats-lossless Raw Authority V2 replay differs from its external pin")
        bundle.require_complete_terminal_selection()
        selected = canonical_raw_request_observations(
            bundle.observations,
            selection="selected_terminal",
        )
        objects_by_sha = {item.object_sha256: item for item in bundle.objects}
        if len(objects_by_sha) != len(bundle.objects):
            _fail("stats-lossless Raw parser-input inventory duplicates one identity")
        occurrences_by_observation, landings_by_observation = _group_observation_children(bundle)
        result: list[StatsLosslessValueAuthorityV1] = []
        for observation in selected:
            if observation.attempt.source_family != "stats":
                continue
            observation_sha256 = observation.attempt.observation_sha256
            occurrences = occurrences_by_observation[observation_sha256]
            landings = landings_by_observation[observation_sha256]
            if not any(item.landing_semantic == "conditional_lossless" for item in landings):
                continue
            result.append(
                _build_one(
                    bundle=bundle,
                    observation=observation,
                    occurrences=occurrences,
                    landings=landings,
                    objects_by_sha=objects_by_sha,
                )
            )
        return tuple(result)
    except Exception:
        raise IndependentStatsLosslessAuthorityBuilderError(
            "stats-lossless authority construction failed exact independent replay"
        ) from None
