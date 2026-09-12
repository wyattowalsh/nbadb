"""Independent body/bodyless producer for the public result-cell authority."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Never, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

from nbadb.contracts.declared_bodyless_packet_types import (
    DeclaredBodylessPacketV1,
    decode_public_canonical_packet,
    validate_declared_bodyless_packet_bytes,
)
from nbadb.contracts.independent_stats_projection_decoder import (
    DecodedStatsProjectionResultV1,
    decode_stats_projection_response,
    validate_decoded_stats_projection_response,
)
from nbadb.contracts.raw_request_authority import (
    MAX_JSON_NODES,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    decode_parser_input_object,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_request_observation_order import (
    canonical_raw_request_observations,
)
from nbadb.contracts.raw_result_cell_authority import (
    RawNbaApiResultCellV2,
    RawResultCellAuthorityReceiptV2,
    validate_raw_result_cell_authority,
    validate_raw_result_cell_authority_receipt,
)

__all__ = [
    "IndependentResultCellBuilderError",
    "build_independent_result_cell_authority",
]


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_MAX_AUTHORITIES = 1_000_000
_MAX_RESULT_CELLS = MAX_JSON_NODES
_MAX_SECRET_COUNT = 128
_MAX_SECRET_BYTES = 4096


class IndependentResultCellBuilderError(ValueError):
    """Exact body authority cannot be projected into result cells."""


def _fail(message: str) -> Never:
    raise IndependentResultCellBuilderError(message) from None


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _pin_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > _MAX_AUTHORITIES:
        _fail(f"{label} must be one bounded exact tuple")
    pins = value
    result = tuple(_sha256(item, label=label) for item in pins)
    if len(set(result)) != len(result):
        _fail(f"{label} contains a duplicate identity")
    return result


def _secret_bytes(value: object) -> tuple[bytes, ...]:
    if type(value) not in {tuple, list} or len(cast("Sequence[object]", value)) > (
        _MAX_SECRET_COUNT
    ):
        _fail("known-secret inventory is foreign or over-bound")
    result: list[bytes] = []
    for item in cast("Sequence[object]", value):
        if type(item) is str:
            try:
                encoded = item.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _fail("known-secret inventory contains invalid text")
        elif type(item) is bytes:
            encoded = item
        else:
            _fail("known-secret inventory contains a foreign value")
        if not encoded or len(encoded) > _MAX_SECRET_BYTES:
            _fail("known-secret inventory contains an invalid byte length")
        result.append(bytes(encoded))
    return tuple(result)


def _reject_secrets(payload: bytes, *, known_secrets: tuple[bytes, ...]) -> None:
    if any(secret in payload for secret in known_secrets):
        _fail("result-cell source bytes contain prohibited known-secret material")


def _result_key(value: ResultOccurrenceV2) -> tuple[object, ...]:
    return (
        value.result_name,
        value.duplicate_name_ordinal,
        value.provider_result_ordinal,
    )


def _decoded_result_key(value: DecodedStatsProjectionResultV1) -> tuple[object, ...]:
    return (
        value.result_name,
        value.result_duplicate_ordinal,
        value.provider_result_ordinal,
    )


def _json_array(encoded: str, *, label: str) -> list[object]:
    if type(encoded) is not str:
        _fail(f"{label} must be exact canonical JSON text")
    try:
        raw = encoded.encode("utf-8", errors="strict")
        value = json.loads(raw)
    except (UnicodeEncodeError, json.JSONDecodeError, RecursionError, ValueError):
        _fail(f"{label} cannot be decoded")
    if type(value) is not list:
        _fail(f"{label} must decode to one exact array")
    return cast("list[object]", value)


def _cells_for_rows(
    *,
    observation_sha256: str,
    occurrence: ResultOccurrenceV2,
    headers: list[object],
    rows: list[object],
) -> tuple[RawNbaApiResultCellV2, ...]:
    exact_headers = occurrence.ordered_headers()
    if (
        headers != list(exact_headers)
        or len(rows) != occurrence.row_count
        or len(exact_headers) != occurrence.header_count
    ):
        _fail("decoded result-cell rectangular shape differs from Raw authority")
    cells: list[RawNbaApiResultCellV2] = []
    for row_ordinal, raw_row in enumerate(rows):
        if type(raw_row) is not list or len(raw_row) != len(exact_headers):
            _fail("decoded result-cell row width differs from Raw authority")
        for header_ordinal, value in enumerate(cast("list[object]", raw_row)):
            cells.append(
                RawNbaApiResultCellV2.build(
                    observation_sha256=observation_sha256,
                    occurrence_sha256=occurrence.occurrence_sha256,
                    cell_ordinal=len(cells),
                    row_ordinal=row_ordinal,
                    header_ordinal=header_ordinal,
                    header_name=exact_headers[header_ordinal],
                    value=value,
                )
            )
    if len(cells) != occurrence.cell_count:
        _fail("decoded result-cell denominator differs from Raw authority")
    return tuple(cells)


def _stats_cells(
    *,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    objects_by_sha: dict[str, ParserInputObjectV2],
    known_secrets: tuple[bytes, ...],
) -> tuple[RawNbaApiResultCellV2, ...]:
    eligible = tuple(item for item in occurrences if item.landing_disposition == "wide_only")
    if not eligible:
        return ()
    body_object = objects_by_sha.get(cast("str", observation.body_object_sha256))
    if body_object is None or observation.body_disposition != "public_parser_input":
        _fail("selected stats observation lacks exact parser-input body authority")
    parser_input = decode_parser_input_object(body_object)
    _reject_secrets(parser_input, known_secrets=known_secrets)
    decoded = validate_decoded_stats_projection_response(
        decode_stats_projection_response(
            parser_input,
            endpoint_id=observation.attempt.endpoint_id,
            endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
            provider_authority_sha256=observation.attempt.provider_authority_sha256,
        ),
        parser_input_bytes=parser_input,
    )
    attempt = observation.attempt
    if (
        decoded.parser_input_sha256 != body_object.response_sha256
        or decoded.parser_input_length != body_object.uncompressed_bytes
        or decoded.endpoint_id != attempt.endpoint_id
        or decoded.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
        or decoded.provider_authority_sha256 != attempt.provider_authority_sha256
    ):
        _fail("independent stats decode differs from its exact Raw source authority")
    decoded_by_key: dict[tuple[object, ...], DecodedStatsProjectionResultV1] = {}
    for result in decoded.results:
        key = _decoded_result_key(result)
        if key in decoded_by_key:
            _fail("independent stats decode contains a duplicate result identity")
        decoded_by_key[key] = result
    eligible_keys = tuple(_result_key(item) for item in eligible)
    if len(set(eligible_keys)) != len(eligible_keys) or any(
        key not in decoded_by_key for key in eligible_keys
    ):
        _fail("independent stats result inventory differs from eligible Raw authority")
    cells: list[RawNbaApiResultCellV2] = []
    for occurrence in eligible:
        result = decoded_by_key[_result_key(occurrence)]
        cells.extend(
            _cells_for_rows(
                observation_sha256=observation.attempt.observation_sha256,
                occurrence=occurrence,
                headers=_json_array(result.raw_headers_json, label="stats raw headers"),
                rows=_json_array(result.raw_rows_json, label="stats raw rows"),
            )
        )
    return tuple(cells)


def _static_headers(packet: DeclaredBodylessPacketV1) -> list[object]:
    schema = decode_public_canonical_packet(packet.frozen_static_schema_json.encode("utf-8"))
    if type(schema) is not list:
        _fail("declared-bodyless frozen schema is not an exact field array")
    headers: list[object] = []
    for ordinal, item in enumerate(cast("list[object]", schema)):
        if type(item) is not dict:
            _fail("declared-bodyless frozen schema contains a foreign field")
        row = cast("dict[object, object]", item)
        if row.get("ordinal") != ordinal or type(row.get("name")) is not str:
            _fail("declared-bodyless frozen schema field identity is invalid")
        headers.append(row["name"])
    return headers


def _static_cells(
    *,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    packet: DeclaredBodylessPacketV1,
    packet_bytes: bytes,
    known_secrets: Sequence[str | bytes],
) -> tuple[RawNbaApiResultCellV2, ...]:
    validated = validate_declared_bodyless_packet_bytes(
        packet,
        packet_bytes=packet_bytes,
        expected_observation_sha256=observation.attempt.observation_sha256,
        expected_observation_record_sha256=observation.observation_record_sha256,
        expected_packet_authority_sha256=packet.packet_authority_sha256,
        known_secrets=known_secrets,
    )
    if validated != packet:
        _fail("declared-bodyless packet differs from exact byte replay")
    attempt = observation.attempt
    if (
        packet.attempt_sha256 != attempt.attempt_sha256
        or packet.logical_receipt_sha256 != observation.logical_receipt_sha256
        or packet.endpoint_id != attempt.endpoint_id
        or packet.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
        or packet.provider_authority_sha256 != attempt.provider_authority_sha256
        or packet.source_sha != attempt.source_sha
        or packet.run_id != attempt.run_id
        or packet.run_attempt != attempt.run_attempt
        or packet.chain_id != attempt.chain_id
        or packet.lane_id != attempt.lane_id
    ):
        _fail("declared-bodyless packet provenance differs from its Raw observation")
    wide = tuple(item for item in occurrences if item.landing_disposition == "wide_only")
    if len(wide) != 1 or len(occurrences) != 1:
        _fail("declared-bodyless observation lacks one exact rectangular occurrence")
    rows = decode_public_canonical_packet(packet_bytes, known_secrets=known_secrets)
    if type(rows) is not list:
        _fail("declared-bodyless packet is not an exact row array")
    return _cells_for_rows(
        observation_sha256=observation.attempt.observation_sha256,
        occurrence=wide[0],
        headers=_static_headers(packet),
        rows=cast("list[object]", rows),
    )


def build_independent_result_cell_authority(
    raw_bundle: object,
    *,
    expected_raw_authority_bundle_sha256: object,
    declared_bodyless_packets: object,
    expected_declared_bodyless_packet_authority_sha256s: object,
    declared_bodyless_packet_bytes: object,
    known_secrets: Sequence[str | bytes] = (),
) -> RawResultCellAuthorityReceiptV2:
    """Decode every selected stats/static rectangular result from source bytes."""

    raw_pin = _sha256(expected_raw_authority_bundle_sha256, label="expected Raw bundle")
    packet_pins = _pin_tuple(
        expected_declared_bodyless_packet_authority_sha256s,
        label="expected declared-bodyless packet pin",
    )
    if type(raw_bundle) is not RawRequestAuthorityBundleV2:
        _fail("result-cell builder requires the exact Raw Authority V2 bundle")
    if _sha256(raw_bundle.bundle_sha256, label="Raw bundle identity") != raw_pin:
        _fail("Raw bundle differs from its external pin")
    if (
        type(declared_bodyless_packets) is not tuple
        or type(declared_bodyless_packet_bytes) is not tuple
    ):
        _fail("declared-bodyless packet inputs must be exact tuples")
    packets = declared_bodyless_packets
    packet_bytes_values = declared_bodyless_packet_bytes
    if (
        len(packets) > _MAX_AUTHORITIES
        or len(packets) != len(packet_pins)
        or len(packets) != len(packet_bytes_values)
        or any(type(item) is not DeclaredBodylessPacketV1 for item in packets)
        or any(type(item) is not bytes for item in packet_bytes_values)
    ):
        _fail("declared-bodyless packet inputs are foreign or incomplete")
    exact_packets = cast("tuple[DeclaredBodylessPacketV1, ...]", packets)
    exact_packet_bytes = cast("tuple[bytes, ...]", packet_bytes_values)
    exact_packet_authority_sha256s = tuple(
        _sha256(
            item.packet_authority_sha256,
            label="declared-bodyless packet identity",
        )
        for item in exact_packets
    )
    if exact_packet_authority_sha256s != packet_pins:
        _fail("declared-bodyless packets differ from their external pins")
    secrets = _secret_bytes(known_secrets)

    try:
        bundle = validate_raw_request_authority_bundle(raw_bundle)
        if (
            type(bundle) is not RawRequestAuthorityBundleV2
            or bundle != raw_bundle
            or bundle.bundle_sha256 != raw_pin
        ):
            _fail("Raw bundle replay differs from its exact external authority")
        bundle.require_complete_terminal_selection()
        selected = canonical_raw_request_observations(
            bundle.observations,
            selection="selected_terminal",
        )
        occurrences_by_observation: dict[str, dict[int, ResultOccurrenceV2]] = {}
        for occurrence in bundle.occurrences:
            by_ordinal = occurrences_by_observation.setdefault(
                occurrence.observation_sha256,
                {},
            )
            if occurrence.occurrence_ordinal in by_ordinal:
                _fail("Raw occurrence inventory duplicates one observation ordinal")
            by_ordinal[occurrence.occurrence_ordinal] = occurrence
        objects_by_sha = {item.object_sha256: item for item in bundle.objects}
        if len(objects_by_sha) != len(bundle.objects):
            _fail("Raw parser-input object inventory repeats one identity")
        expected_cell_count = 0
        for observation in selected:
            for occurrence in occurrences_by_observation.get(
                observation.attempt.observation_sha256,
                {},
            ).values():
                if (
                    observation.attempt.source_family in {"stats", "static"}
                    and occurrence.landing_disposition == "wide_only"
                ):
                    expected_cell_count += occurrence.cell_count
                    if expected_cell_count > _MAX_RESULT_CELLS:
                        _fail("result-cell source authority exceeds its global cell bound")
        packet_by_observation: dict[str, tuple[DeclaredBodylessPacketV1, bytes]] = {}
        for packet, packet_bytes in zip(exact_packets, exact_packet_bytes, strict=True):
            if packet.observation_sha256 in packet_by_observation:
                _fail("declared-bodyless packet inventory duplicates one observation")
            packet_by_observation[packet.observation_sha256] = (packet, packet_bytes)

        cells: list[RawNbaApiResultCellV2] = []
        for observation in selected:
            observation_sha256 = observation.attempt.observation_sha256
            index = occurrences_by_observation.get(observation_sha256, {})
            if set(index) != set(range(len(index))):
                _fail("Raw occurrence ordinals are not contiguous within one observation")
            occurrences = tuple(index[ordinal] for ordinal in range(len(index)))
            if observation.attempt.source_family == "stats":
                cells.extend(
                    _stats_cells(
                        observation=observation,
                        occurrences=occurrences,
                        objects_by_sha=objects_by_sha,
                        known_secrets=secrets,
                    )
                )
            elif observation.attempt.source_family == "static":
                packet_input = packet_by_observation.pop(observation_sha256, None)
                if packet_input is None:
                    _fail("selected static observation lacks exact packet bytes")
                packet, packet_bytes = packet_input
                cells.extend(
                    _static_cells(
                        observation=observation,
                        occurrences=occurrences,
                        packet=packet,
                        packet_bytes=packet_bytes,
                        known_secrets=known_secrets,
                    )
                )
            elif observation.attempt.source_family != "live":
                _fail("selected observation has a foreign source family")
        if packet_by_observation:
            _fail("declared-bodyless packet inventory contains an orphan observation")
        receipt = validate_raw_result_cell_authority(bundle, tuple(cells))
        if (
            type(receipt) is not RawResultCellAuthorityReceiptV2
            or receipt.raw_authority_bundle_sha256 != raw_pin
        ):
            _fail("result-cell receipt differs from its exact Raw authority")
        exact_receipt = validate_raw_result_cell_authority_receipt(bundle, receipt)
        if exact_receipt != receipt:
            _fail("result-cell receipt differs after exact authority replay")
        return exact_receipt
    except Exception:
        raise IndependentResultCellBuilderError(
            "result-cell source authorities failed exact independent reconstruction"
        ) from None
