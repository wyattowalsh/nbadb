"""Bundle-scoped builder for the value-free route-field landing relation.

This join is deliberately downstream of the value authorities.  It consumes
only their public identity scalars, ordered field authorities, and selected
occurrence summaries.  Provider values remain outside this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, ClassVar, Final, Never, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

from nbadb.contracts.lossless_ownership import (
    LosslessOwnershipAuthorityV1,
    LosslessOwnershipPartitionV1,
)
from nbadb.contracts.public_value_types import (
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.raw_request_authority import (
    MAX_AUTHORITY_ROWS,
    ObservationRouteLandingV2,
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_result_cell_authority import RawResultCellAuthorityReceiptV2
from nbadb.contracts.route_field_canonical_alias import (
    MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES,
    RouteFieldCanonicalAliasFieldV1,
    RouteFieldCanonicalAliasReceiptV1,
)
from nbadb.contracts.route_field_landing_authority import (
    MAX_ROUTE_FIELD_LANDING_RECEIPTS,
    MAX_ROUTE_FIELD_LANDING_ROWS,
    RawNbaApiRouteFieldLandingV1,
)
from nbadb.contracts.typed_field_value_receipt import (
    MAX_JSON_DEPTH,
    MAX_ROUTE_BINARY_BYTES,
    MAX_ROUTE_CANONICAL_BYTES,
    MAX_ROUTE_CELLS,
    MAX_ROUTE_CONTAINER_ITEMS,
    MAX_ROUTE_FIELDS,
    MAX_ROUTE_OCCURRENCES,
    MAX_ROUTE_ROWS,
    MAX_ROUTE_VALUE_BYTES,
    MAX_ROUTE_VALUE_NODES,
    LandingFieldAuthorityV2,
    RouteFieldLandingReceiptV2,
    SourceOccurrenceAuthorityV2,
)

__all__ = [
    "RAW_NBA_API_ROUTE_FIELD_LANDING_AUTHORITY_RECEIPT_COLUMNS",
    "RawNbaApiRouteFieldLandingAuthorityReceiptV1",
    "RawNbaApiRouteFieldLandingAuthorityV1",
    "RouteFieldLandingBuilderError",
    "build_raw_nba_api_route_field_landing_authority",
]


_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_RECEIPT_KIND: Final = "raw_nba_api_route_field_landing_authority_receipt_v1"
_SELECTED_OBSERVATION_ROOT_KIND: Final = "raw_nba_api_route_field_selected_observations_v1"
_RAW_LANDING_ROOT_KIND: Final = "raw_nba_api_route_field_raw_landings_v1"
_ROUTE_RECEIPT_ROOT_KIND: Final = "raw_nba_api_route_field_route_receipts_v1"
_ALIAS_RECEIPT_ROOT_KIND: Final = "raw_nba_api_route_field_alias_receipts_v1"
_ASSIGNMENT_ROOT_KIND: Final = "raw_nba_api_route_field_assignments_v1"
_LANDING_FIELD_ROOT_KIND: Final = "raw_nba_api_route_field_rows_v1"
_MAX_RECEIPT_BYTES: Final = 64 * 1024

_SOURCE_INPUT_BY_DISPOSITION: Final = {
    "public_parser_input": "parser_input_body",
    "declared_bodyless": "declared_bodyless_packet",
}
_LANDING_SEMANTIC_BY_SOURCE_SHAPE: Final = {
    "result_occurrence_bound": "occurrence_bound",
    "selected_result_bound": "conditional_lossless",
    "body_node_bound": "conditional_lossless",
    "hybrid_result_body_bound": "conditional_lossless",
    "live_lossless_bound": "conditional_lossless",
    "response_fixed_zero": "response_fixed_zero",
}
_RESULT_REPRESENTATION_BY_SOURCE_SHAPE: Final = {
    "result_occurrence_bound": "rectangular_result_cells_v1",
    "selected_result_bound": "stats_lossless_records_v1",
    "hybrid_result_body_bound": "stats_lossless_records_v1",
    "live_lossless_bound": "live_lossless_nodes_v1",
}
_LOSSLESS_RESULT_REPRESENTATIONS: Final = frozenset(
    {"stats_lossless_records_v1", "live_lossless_nodes_v1"}
)
_RESIDUAL_SOURCE_SHAPES: Final = frozenset(
    {"body_node_bound", "hybrid_result_body_bound", "live_lossless_bound"}
)
_DECODER_BY_SOURCE_FAMILY: Final = {
    "stats": "stats_result_set_rows_v1",
    "live": "live_record_projection_v1",
    "static": "static_dataset_records_v1",
}
_CONDITIONAL_DECODER_BY_SOURCE_SHAPE: Final = {
    "selected_result_bound": "conditional_selected_result_rows_v2",
    "body_node_bound": "conditional_body_node_rows_v2",
    "hybrid_result_body_bound": "conditional_hybrid_result_body_rows_v2",
    "live_lossless_bound": "conditional_live_lossless_rows_v2",
}

RAW_NBA_API_ROUTE_FIELD_LANDING_AUTHORITY_RECEIPT_COLUMNS: Final = (
    "schema_version",
    "receipt_sha256",
    "raw_authority_bundle_sha256",
    "result_cell_authority_sha256",
    "lossless_ownership_receipt_sha256",
    "expected_unit_inventory_sha256",
    "expected_unit_count",
    "expected_unit_root_sha256",
    "representation_assignment_count",
    "representation_assignment_root_sha256",
    "selected_observation_count",
    "selected_observation_root_sha256",
    "raw_route_landing_count",
    "raw_route_landing_root_sha256",
    "direct_route_count",
    "route_receipt_count",
    "route_receipt_root_sha256",
    "alias_route_count",
    "alias_receipt_count",
    "alias_receipt_root_sha256",
    "field_binding_row_count",
    "route_only_row_count",
    "landing_field_count",
    "landing_field_root_sha256",
)


class RouteFieldLandingBuilderError(ValueError):
    """The route-field authority cannot be derived from its exact inputs."""


def _fail(message: str) -> Never:
    raise RouteFieldLandingBuilderError(message)


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _count(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one bounded nonnegative exact integer")
    return value


def _canonical_json_bytes(value: object, *, maximum_bytes: int = _MAX_RECEIPT_BYTES) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("route-field builder identity is not exact canonical JSON")
    if not encoded or len(encoded) > maximum_bytes:
        _fail("route-field builder identity exceeds its canonical byte bound")
    return encoded


def _canonical_sha256(value: object, *, maximum_bytes: int = _MAX_RECEIPT_BYTES) -> str:
    return hashlib.sha256(_canonical_json_bytes(value, maximum_bytes=maximum_bytes)).hexdigest()


def _ordered_root(
    *,
    kind: str,
    raw_authority_bundle_sha256: str,
    item_sha256s: tuple[str, ...],
    maximum: int,
) -> str:
    if type(item_sha256s) is not tuple or len(item_sha256s) > maximum:
        _fail("route-field ordered-root inventory is mutable or over-bound")
    for item in item_sha256s:
        _sha256(item, label="route-field ordered-root member")
    # Stream the exact sort-key canonical JSON object so large admitted row
    # inventories do not require a second materialized list.
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(item_sha256s)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, item in enumerate(item_sha256s):
        if ordinal:
            digest.update(b",")
        digest.update(b'"')
        digest.update(item.encode("ascii"))
        digest.update(b'"')
    digest.update(b'],"kind":')
    digest.update(json.dumps(kind, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    digest.update(b',"raw_authority_bundle_sha256":"')
    digest.update(raw_authority_bundle_sha256.encode("ascii"))
    digest.update(b'"}')
    return digest.hexdigest()


def _checked_add(left: int, right: int, *, maximum: int, label: str) -> int:
    _count(left, label=label, maximum=maximum)
    _count(right, label=label, maximum=maximum)
    if left > maximum - right:
        _fail(f"{label} exceeds its explicit aggregate bound")
    return left + right


def _checked_product(left: int, right: int, *, maximum: int, label: str) -> int:
    _count(left, label=label, maximum=maximum)
    _count(right, label=label, maximum=max(maximum, MAX_ROUTE_FIELDS))
    if left and right > maximum // left:
        _fail(f"{label} exceeds its explicit product bound")
    return left * right


_ObservationOrderKey = tuple[str, str, int, int, int, str, str, int, int, str]


def _observation_order_key(observation: RequestObservationV2) -> _ObservationOrderKey:
    attempt = observation.attempt
    return (
        attempt.logical_invocation_sha256,
        attempt.semantic_request_sha256,
        attempt.provider_call_ordinal,
        0 if attempt.page_ordinal is None else 1,
        0 if attempt.page_ordinal is None else attempt.page_ordinal,
        attempt.provider_call_role,
        attempt.provider_call_sha256,
        attempt.retry_ordinal,
        attempt.request_ordinal,
        attempt.observation_sha256,
    )


def _source_input_kind(observation: RequestObservationV2) -> str:
    result = _SOURCE_INPUT_BY_DISPOSITION.get(observation.body_disposition)
    if result is None:
        _fail("selected observation lacks one admitted public source-input disposition")
    return result


def _exact_inventory(value: object) -> ExpectedValueUnitInventoryV1:
    if type(value) is not ExpectedValueUnitInventoryV1:
        _fail("route-field builder requires the exact expected-unit inventory DTO")
    try:
        replayed = ExpectedValueUnitInventoryV1.from_row(value.to_row())
    except (TypeError, ValueError) as exc:
        raise RouteFieldLandingBuilderError(
            "expected-unit inventory fails exact row replay"
        ) from exc
    if replayed != value:
        _fail("expected-unit inventory differs from exact row replay")
    return replayed


def _exact_assignments(
    inventory: ExpectedValueUnitInventoryV1,
    value: object,
) -> tuple[ValueRepresentationAssignmentV1, ...]:
    if type(value) is not tuple or len(value) > MAX_PUBLIC_VALUE_EXPECTED_UNITS:
        _fail("route-field assignment inventory is mutable or over-bound")
    assignments = value
    if len(assignments) != inventory.unit_count:
        _fail("route-field assignment denominator differs from expected units")
    rebuilt: list[ValueRepresentationAssignmentV1] = []
    seen: set[str] = set()
    for ordinal, (unit, item) in enumerate(zip(inventory.units, assignments, strict=True)):
        if type(item) is not ValueRepresentationAssignmentV1:
            _fail("route-field assignment inventory contains a foreign DTO")
        assignment = item
        try:
            replayed = ValueRepresentationAssignmentV1.from_row(assignment.to_row())
            replayed.validate_for_unit(unit)
        except (TypeError, ValueError) as exc:
            raise RouteFieldLandingBuilderError(
                "route-field assignment fails exact expected-unit replay"
            ) from exc
        if (
            replayed != assignment
            or replayed.unit_ordinal != ordinal
            or replayed.assignment_sha256 in seen
        ):
            _fail("route-field assignments are duplicated, foreign, or reordered")
        seen.add(replayed.assignment_sha256)
        rebuilt.append(replayed)
    return tuple(rebuilt)


def _exact_ownership(value: object) -> LosslessOwnershipAuthorityV1:
    if type(value) is not LosslessOwnershipAuthorityV1:
        _fail("route-field builder requires the exact ownership authority DTO")
    authority = value
    try:
        replayed = LosslessOwnershipAuthorityV1(
            receipt=authority.receipt,
            expected_unit_inventory=authority.expected_unit_inventory,
            representation_assignments=authority.representation_assignments,
            observations=authority.observations,
            partitions=authority.partitions,
            bindings=authority.bindings,
        )
    except (TypeError, ValueError) as exc:
        raise RouteFieldLandingBuilderError(
            "lossless ownership authority fails exact closure replay"
        ) from exc
    if replayed != authority:
        _fail("lossless ownership authority differs from exact closure replay")
    return replayed


def _result_cell_authority_sha256(
    value: object,
    *,
    raw_authority_bundle_sha256: str,
) -> str:
    if type(value) is not RawResultCellAuthorityReceiptV2:
        _fail("route-field builder requires the exact result-cell authority receipt")
    receipt = value
    authority_sha256 = _sha256(receipt.authority_sha256, label="result-cell authority")
    bundle_sha256 = _sha256(
        receipt.raw_authority_bundle_sha256,
        label="result-cell raw authority bundle",
    )
    proof_sha256 = _sha256(
        receipt.public_table_proof_sha256,
        label="result-cell public-table proof",
    )
    expected = _canonical_sha256(
        {
            "schema_version": RawResultCellAuthorityReceiptV2.schema_version,
            "kind": RawResultCellAuthorityReceiptV2.kind,
            "raw_authority_bundle_sha256": bundle_sha256,
            "public_table_proof_sha256": proof_sha256,
        }
    )
    if bundle_sha256 != raw_authority_bundle_sha256 or authority_sha256 != expected:
        _fail("result-cell receipt is foreign or differs from its scalar identity")
    return authority_sha256


def _replay_field(
    value: object,
    *,
    ordinal: int,
    route_id: str,
    staging_key: str,
    field_fate_structure_sha256: str,
) -> LandingFieldAuthorityV2:
    if type(value) is not LandingFieldAuthorityV2:
        _fail("route receipt contains a foreign field authority")
    field = value
    try:
        replayed = LandingFieldAuthorityV2(
            **{item.name: getattr(field, item.name) for item in fields(LandingFieldAuthorityV2)}
        )
    except (TypeError, ValueError) as exc:
        raise RouteFieldLandingBuilderError(
            "route field authority fails exact reconstruction"
        ) from exc
    if (
        replayed != field
        or replayed.storage_ordinal != ordinal
        or replayed.route_id != route_id
        or replayed.staging_key != staging_key
        or replayed.field_fate_structure_sha256 != field_fate_structure_sha256
    ):
        _fail("route field authority is foreign, relabeled, or reordered")
    return replayed


def _replay_selected_occurrence(
    value: object,
    *,
    raw_authority_bundle_sha256: str,
    source_family: str,
    endpoint_id: str,
) -> SourceOccurrenceAuthorityV2:
    if type(value) is not SourceOccurrenceAuthorityV2:
        _fail("route receipt contains a foreign selected-occurrence authority")
    occurrence = value
    try:
        replayed = SourceOccurrenceAuthorityV2(
            **{
                item.name: getattr(occurrence, item.name)
                for item in fields(SourceOccurrenceAuthorityV2)
            }
        )
    except (TypeError, ValueError) as exc:
        raise RouteFieldLandingBuilderError(
            "selected-occurrence authority fails exact reconstruction"
        ) from exc
    if (
        replayed != occurrence
        or replayed.raw_bundle_sha256 != raw_authority_bundle_sha256
        or replayed.source_family != source_family
        or replayed.endpoint_id != endpoint_id
    ):
        _fail("selected-occurrence authority is foreign or relabeled")
    return replayed


def _selected_occurrence_matches_raw(
    selected: SourceOccurrenceAuthorityV2,
    *,
    raw_authority_bundle_sha256: str,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
) -> bool:
    try:
        ordered_headers = occurrence.ordered_headers()
        canonical_route_ids = occurrence.canonical_route_ids()
        committed_staging_receipts = tuple(occurrence.committed_staging_receipts_by_route().items())
    except (TypeError, ValueError):
        return False
    return (
        selected.raw_bundle_sha256 == raw_authority_bundle_sha256
        and selected.observation_sha256 == observation.attempt.observation_sha256
        and selected.occurrence_sha256 == occurrence.occurrence_sha256
        and selected.source_family == observation.attempt.source_family
        and selected.endpoint_id == observation.attempt.endpoint_id
        and selected.occurrence_ordinal == occurrence.occurrence_ordinal
        and selected.result_name == occurrence.result_name
        and selected.duplicate_name_ordinal == occurrence.duplicate_name_ordinal
        and selected.provider_result_ordinal == occurrence.provider_result_ordinal
        and selected.canonical_result_ordinal == occurrence.canonical_result_ordinal
        and selected.json_path == occurrence.json_path
        and selected.container_kind == occurrence.container_kind
        and selected.presence == occurrence.presence
        and selected.ordered_headers == ordered_headers
        and selected.ordered_headers_sha256 == occurrence.ordered_headers_sha256
        and selected.header_count == occurrence.header_count
        and selected.row_count == occurrence.row_count
        and selected.cell_count == occurrence.cell_count
        and selected.node_count == occurrence.node_count
        and selected.container_count == occurrence.container_count
        and selected.missing_count == occurrence.missing_count
        and selected.null_count == occurrence.null_count
        and selected.parent_state_sha256 == occurrence.parent_state_sha256
        and selected.output_sha256 == occurrence.output_sha256
        and selected.canonical_route_ids == canonical_route_ids
        and selected.canonical_route_ids_sha256 == occurrence.canonical_route_ids_sha256
        and selected.committed_staging_receipts == committed_staging_receipts
        and selected.committed_staging_receipts_sha256
        == occurrence.committed_staging_receipts_sha256
        and selected.landing_disposition == occurrence.landing_disposition
        and selected.logical_result_receipt_sha256 == occurrence.logical_result_receipt_sha256
        and selected.route_receipt_sha256 == occurrence.route_receipt_sha256
    )


def _route_receipt_identity(receipt: RouteFieldLandingReceiptV2) -> dict[str, object]:
    return {
        "schema_version": RouteFieldLandingReceiptV2.schema_version,
        "kind": RouteFieldLandingReceiptV2.kind,
        "canonical_frame_format": receipt.canonical_frame_format,
        "frame_content_hash_contract": receipt.frame_content_hash_contract,
        "frame_schema_hash_contract": receipt.frame_schema_hash_contract,
        "readback_receipt_sha256": receipt.readback_receipt_sha256,
        "receipt_root_sha256": receipt.receipt_root_sha256,
        "raw_bundle_sha256": receipt.raw_bundle_sha256,
        "field_fate_structure_sha256": receipt.field_fate_structure_sha256,
        "route_id": receipt.route_id,
        "staging_key": receipt.staging_key,
        "source_family": receipt.source_family,
        "decoder_kind": receipt.decoder_kind,
        "source_shape": receipt.source_shape,
        "endpoint_id": receipt.endpoint_id,
        "conditional_authority_sha256": receipt.conditional_authority_sha256,
        "row_partition_receipt_sha256": receipt.row_partition_receipt_sha256,
        "row_count": receipt.row_count,
        "occurrence_partition_count": receipt.occurrence_partition_count,
        "selected_occurrence_count": receipt.selected_occurrence_count,
        "field_count": receipt.field_count,
        "cell_count": receipt.cell_count,
        "source_verified_cell_count": receipt.source_verified_cell_count,
        "storage_readback_only_cell_count": receipt.storage_readback_only_cell_count,
        "selected_occurrence_sha256s": list(receipt.selected_occurrence_sha256s),
        "row_slice_receipt_sha256s": list(receipt.row_slice_receipt_sha256s),
        "value_node_count": receipt.value_node_count,
        "value_max_depth": receipt.value_max_depth,
        "value_utf8_bytes": receipt.value_utf8_bytes,
        "value_binary_bytes": receipt.value_binary_bytes,
        "value_container_items": receipt.value_container_items,
        "value_canonical_bytes": receipt.value_canonical_bytes,
        "fields_sha256": receipt.fields_sha256,
        "occurrences_sha256": receipt.occurrences_sha256,
        "selected_occurrences_sha256": receipt.selected_occurrences_sha256,
        "values_sha256": receipt.values_sha256,
        "conditional_rows_sha256": receipt.conditional_rows_sha256,
    }


@dataclass(frozen=True, slots=True)
class _SafeRouteReceipt:
    receipt: RouteFieldLandingReceiptV2
    fields: tuple[LandingFieldAuthorityV2, ...]
    selected_occurrences: tuple[SourceOccurrenceAuthorityV2, ...]


def _safe_route_receipt(
    value: object,
    *,
    raw_authority_bundle_sha256: str,
) -> _SafeRouteReceipt:
    if type(value) is not RouteFieldLandingReceiptV2:
        _fail("route receipt inventory contains a foreign DTO")
    receipt = value
    for label, digest in (
        ("route readback receipt", receipt.readback_receipt_sha256),
        ("route committed receipt root", receipt.receipt_root_sha256),
        ("route raw bundle", receipt.raw_bundle_sha256),
        ("route field fate", receipt.field_fate_structure_sha256),
        ("route row partition", receipt.row_partition_receipt_sha256),
        ("route fields", receipt.fields_sha256),
        ("route occurrences", receipt.occurrences_sha256),
        ("route selected occurrences", receipt.selected_occurrences_sha256),
        ("route values", receipt.values_sha256),
        ("route conditional rows", receipt.conditional_rows_sha256),
        ("route landing receipt", receipt.landing_receipt_sha256),
    ):
        _sha256(digest, label=label)
    if receipt.raw_bundle_sha256 != raw_authority_bundle_sha256:
        _fail("route receipt belongs to a foreign Raw bundle")
    if type(receipt.route_id) is not str or type(receipt.staging_key) is not str:
        _fail("route receipt has non-exact route identity")
    if type(receipt.source_family) is not str or type(receipt.endpoint_id) is not str:
        _fail("route receipt has non-exact source identity")
    if receipt.source_shape not in _LANDING_SEMANTIC_BY_SOURCE_SHAPE:
        _fail("route receipt source shape is outside the closed route-field domain")
    if any(
        type(item) is not str
        for item in (
            receipt.canonical_frame_format,
            receipt.frame_content_hash_contract,
            receipt.frame_schema_hash_contract,
        )
    ):
        _fail("route receipt frame contract is not exact text")
    if receipt.source_shape == "result_occurrence_bound":
        expected_decoder = _DECODER_BY_SOURCE_FAMILY.get(receipt.source_family)
        if (
            expected_decoder is None
            or receipt.decoder_kind != expected_decoder
            or receipt.conditional_authority_sha256 is not None
        ):
            _fail("route receipt result decoder relabels its source family")
    elif receipt.source_shape == "response_fixed_zero":
        if (
            receipt.source_family not in _DECODER_BY_SOURCE_FAMILY
            or receipt.decoder_kind != "response_fixed_zero_v2"
            or receipt.conditional_authority_sha256 is not None
        ):
            _fail("route receipt fixed-zero decoder relabels its source family")
    else:
        expected_family = "live" if receipt.source_shape == "live_lossless_bound" else "stats"
        expected_decoder = _CONDITIONAL_DECODER_BY_SOURCE_SHAPE.get(receipt.source_shape)
        if (
            receipt.source_family != expected_family
            or receipt.decoder_kind != expected_decoder
            or receipt.conditional_authority_sha256 is None
        ):
            _fail("route receipt conditional decoder is rebound")
        _sha256(
            receipt.conditional_authority_sha256,
            label="route conditional authority",
        )
    for label, item, maximum in (
        ("route row count", receipt.row_count, MAX_ROUTE_ROWS),
        ("route occurrence count", receipt.occurrence_partition_count, MAX_ROUTE_OCCURRENCES),
        (
            "route selected occurrence count",
            receipt.selected_occurrence_count,
            MAX_ROUTE_OCCURRENCES,
        ),
        ("route field count", receipt.field_count, MAX_ROUTE_FIELDS),
        ("route cell count", receipt.cell_count, MAX_ROUTE_CELLS),
        ("route source-verified count", receipt.source_verified_cell_count, MAX_ROUTE_CELLS),
        (
            "route storage-readback-only count",
            receipt.storage_readback_only_cell_count,
            MAX_ROUTE_CELLS,
        ),
        ("route value-node count", receipt.value_node_count, MAX_ROUTE_VALUE_NODES),
        ("route UTF-8 byte count", receipt.value_utf8_bytes, MAX_ROUTE_VALUE_BYTES),
        ("route binary byte count", receipt.value_binary_bytes, MAX_ROUTE_BINARY_BYTES),
        ("route container-item count", receipt.value_container_items, MAX_ROUTE_CONTAINER_ITEMS),
        ("route canonical byte count", receipt.value_canonical_bytes, MAX_ROUTE_CANONICAL_BYTES),
    ):
        _count(item, label=label, maximum=maximum)
    _count(receipt.value_max_depth, label="route value depth", maximum=MAX_JSON_DEPTH)
    if receipt.cell_count != _checked_product(
        receipt.row_count,
        receipt.field_count,
        maximum=MAX_ROUTE_CELLS,
        label="route cell denominator",
    ):
        _fail("route receipt cell denominator differs from row x field")
    if (
        receipt.source_verified_cell_count + receipt.storage_readback_only_cell_count
        != receipt.cell_count
    ):
        _fail("route receipt cell authority counts do not conserve the denominator")
    if type(receipt.field_authorities) is not tuple or len(receipt.field_authorities) != (
        receipt.field_count
    ):
        _fail("route receipt field denominator is mutable or incomplete")
    if (
        type(receipt.selected_occurrence_authorities) is not tuple
        or len(receipt.selected_occurrence_authorities) != receipt.selected_occurrence_count
    ):
        _fail("route receipt selected-occurrence denominator is mutable or incomplete")
    if (
        type(receipt.selected_occurrence_sha256s) is not tuple
        or len(receipt.selected_occurrence_sha256s) != receipt.selected_occurrence_count
    ):
        _fail("route receipt selected-occurrence identity denominator is incomplete")
    if type(receipt.row_slice_receipt_sha256s) is not tuple:
        _fail("route receipt row-slice denominator is mutable")
    for digest in receipt.row_slice_receipt_sha256s:
        _sha256(digest, label="route row-slice receipt")
    expected_slice_count = (
        receipt.occurrence_partition_count
        if receipt.source_shape == "result_occurrence_bound"
        else 0
        if receipt.source_shape == "response_fixed_zero"
        else receipt.row_count
    )
    if (
        len(receipt.row_slice_receipt_sha256s) != expected_slice_count
        or len(set(receipt.row_slice_receipt_sha256s)) != len(receipt.row_slice_receipt_sha256s)
        or (
            receipt.source_shape == "result_occurrence_bound"
            and receipt.selected_occurrence_count != receipt.occurrence_partition_count
        )
    ):
        _fail("route receipt occurrence/slice denominator is incomplete or collapsed")
    fields_exact = tuple(
        _replay_field(
            item,
            ordinal=ordinal,
            route_id=receipt.route_id,
            staging_key=receipt.staging_key,
            field_fate_structure_sha256=receipt.field_fate_structure_sha256,
        )
        for ordinal, item in enumerate(receipt.field_authorities)
    )
    selected_exact = tuple(
        _replay_selected_occurrence(
            item,
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            source_family=receipt.source_family,
            endpoint_id=receipt.endpoint_id,
        )
        for item in receipt.selected_occurrence_authorities
    )
    selected_sha256s = tuple(item.occurrence_sha256 for item in selected_exact)
    if (
        selected_sha256s != receipt.selected_occurrence_sha256s
        or len(set(selected_sha256s)) != len(selected_sha256s)
        or receipt.fields_sha256
        != _canonical_sha256(
            [item.to_dict() for item in fields_exact],
            maximum_bytes=MAX_ROUTE_CANONICAL_BYTES,
        )
        or receipt.selected_occurrences_sha256
        != _canonical_sha256(
            [item.to_dict() for item in selected_exact],
            maximum_bytes=MAX_ROUTE_CANONICAL_BYTES,
        )
        or receipt.landing_receipt_sha256
        != _canonical_sha256(
            _route_receipt_identity(receipt),
            maximum_bytes=MAX_ROUTE_CANONICAL_BYTES,
        )
    ):
        _fail("route receipt safe projection differs from its exact scalar/child roots")
    if receipt.source_shape == "response_fixed_zero" and any(
        (
            receipt.row_count,
            receipt.cell_count,
            receipt.selected_occurrence_count,
            receipt.occurrence_partition_count,
        )
    ):
        _fail("fixed-zero route receipt fabricates rows, cells, or occurrences")
    return _SafeRouteReceipt(
        receipt=receipt,
        fields=fields_exact,
        selected_occurrences=selected_exact,
    )


def _receipt_matches_landing(
    safe: _SafeRouteReceipt,
    landing: ObservationRouteLandingV2,
    observation: RequestObservationV2,
) -> bool:
    receipt = safe.receipt
    return (
        receipt.route_id == landing.route_id
        and receipt.staging_key == landing.staging_key
        and receipt.receipt_root_sha256 == landing.receipt_root_sha256
        and receipt.row_count == landing.persisted_row_count
        and receipt.canonical_frame_format == landing.canonical_frame_format
        and receipt.frame_content_hash_contract == landing.frame_content_hash_contract
        and receipt.frame_schema_hash_contract == landing.frame_schema_hash_contract
        and receipt.source_family == observation.attempt.source_family
        and receipt.endpoint_id == observation.attempt.endpoint_id
        and _LANDING_SEMANTIC_BY_SOURCE_SHAPE[receipt.source_shape] == landing.landing_semantic
    )


def _safe_receipt_match_key(safe: _SafeRouteReceipt) -> tuple[object, ...]:
    receipt = safe.receipt
    return (
        receipt.route_id,
        receipt.staging_key,
        receipt.receipt_root_sha256,
        receipt.row_count,
        receipt.canonical_frame_format,
        receipt.frame_content_hash_contract,
        receipt.frame_schema_hash_contract,
        receipt.source_family,
        receipt.endpoint_id,
        _LANDING_SEMANTIC_BY_SOURCE_SHAPE[receipt.source_shape],
    )


def _raw_landing_match_key(
    landing: ObservationRouteLandingV2,
    observation: RequestObservationV2,
) -> tuple[object, ...]:
    return (
        landing.route_id,
        landing.staging_key,
        landing.receipt_root_sha256,
        landing.persisted_row_count,
        landing.canonical_frame_format,
        landing.frame_content_hash_contract,
        landing.frame_schema_hash_contract,
        observation.attempt.source_family,
        observation.attempt.endpoint_id,
        landing.landing_semantic,
    )


def _unit_partition_index(
    ownership: LosslessOwnershipAuthorityV1,
) -> dict[str, LosslessOwnershipPartitionV1]:
    result: dict[str, LosslessOwnershipPartitionV1] = {}
    for partition in ownership.partitions:
        if partition.unit_sha256 is None:
            continue
        if partition.unit_sha256 in result:
            _fail("ownership authority binds one expected unit to several partitions")
        result[partition.unit_sha256] = partition
    return result


def _units_for_receipt(
    *,
    safe: _SafeRouteReceipt,
    landing: ObservationRouteLandingV2,
    units_by_occurrence: dict[tuple[str, str], ExpectedValueUnitV1],
    response_unit_by_observation: dict[str, ExpectedValueUnitV1],
    response_partition_kind_by_observation: Mapping[str, str],
    assignments_by_unit: dict[str, ValueRepresentationAssignmentV1],
    partitions_by_unit: dict[str, LosslessOwnershipPartitionV1],
) -> tuple[ExpectedValueUnitV1, ...]:
    receipt = safe.receipt
    selected_units: list[ExpectedValueUnitV1] = []
    superseded_occurrence_count = 0
    result_representation = _RESULT_REPRESENTATION_BY_SOURCE_SHAPE.get(receipt.source_shape)
    if result_representation is not None:
        for selected in safe.selected_occurrences:
            unit = units_by_occurrence.get(
                (selected.observation_sha256, selected.occurrence_sha256)
            )
            if unit is None:
                _fail("route receipt selects an occurrence outside expected-unit authority")
            assignment = assignments_by_unit[unit.unit_sha256]
            if assignment.representation_kind != result_representation:
                # Raw V2 retains the physical wide landing even when public
                # ownership selects the exact conditional lossless copy.  The
                # receipt remains part of the Raw landing/receipt roots, while
                # the final bundle-wide owner-set closure below proves that a
                # conditional route owns every superseded occurrence unit.
                if (
                    receipt.source_shape == "result_occurrence_bound"
                    and assignment.representation_kind in _LOSSLESS_RESULT_REPRESENTATIONS
                ):
                    superseded_occurrence_count += 1
                    continue
                _fail("route receipt source shape conflicts with occurrence representation")
            selected_units.append(unit)
    elif safe.selected_occurrences:
        _fail("response-only route receipt fabricates selected result occurrences")
    if receipt.source_shape in _RESIDUAL_SOURCE_SHAPES:
        response = response_unit_by_observation.get(landing.observation_sha256)
        if response is None or response.unit_kind != "response_residual":
            _fail("lossless response route lacks its positive residual expected unit")
        assignment = assignments_by_unit[response.unit_sha256]
        if assignment.representation_kind != "response_lossless_records_v1":
            _fail("lossless response route conflicts with residual representation")
        selected_units.append(response)
    elif receipt.source_shape == "response_fixed_zero":
        response_partition_kind = response_partition_kind_by_observation.get(
            landing.observation_sha256
        )
        response = response_unit_by_observation.get(landing.observation_sha256)
        if response_partition_kind == "response_fixed_zero":
            if response is None or response.unit_kind != "response_fixed_zero":
                _fail("fixed-zero route lacks its exact response expected unit")
            assignment = assignments_by_unit[response.unit_sha256]
            partition = partitions_by_unit.get(response.unit_sha256)
            if (
                assignment.representation_kind != "response_fixed_zero_v1"
                or partition is None
                or partition.fixed_zero_landing_sha256 != landing.landing_sha256
            ):
                _fail("fixed-zero route differs from its exact ownership landing")
            selected_units.append(response)
        elif response_partition_kind == "response_residual":
            if response is not None and response.unit_kind != "response_residual":
                _fail("hybrid fixed-zero route conflicts with residual ownership")
        else:
            _fail("fixed-zero route lacks one exact response ownership partition")
    unitless_hybrid_fixed_route = (
        receipt.source_shape == "response_fixed_zero"
        and response_partition_kind_by_observation.get(landing.observation_sha256)
        == "response_residual"
    )
    unitless_superseded_occurrence_route = (
        receipt.source_shape == "result_occurrence_bound"
        and bool(safe.selected_occurrences)
        and superseded_occurrence_count == len(safe.selected_occurrences)
    )
    if not selected_units and not (
        unitless_hybrid_fixed_route or unitless_superseded_occurrence_route
    ):
        _fail("direct route receipt owns no expected value unit")
    result = tuple(selected_units)
    if len({item.unit_sha256 for item in result}) != len(result):
        _fail("one route receipt duplicates an expected unit")
    prior_unit_ordinal = -1
    for item in result:
        if item.unit_ordinal <= prior_unit_ordinal:
            _fail("one route receipt reorders its expected value units")
        prior_unit_ordinal = item.unit_ordinal
    for unit in result:
        partition = partitions_by_unit.get(unit.unit_sha256)
        assignment = assignments_by_unit[unit.unit_sha256]
        if (
            partition is None
            or partition.assignment_sha256 != assignment.assignment_sha256
            or partition.unit_ordinal != unit.unit_ordinal
            or partition.observation_sha256 != unit.observation_sha256
            or partition.partition_kind != unit.unit_kind
        ):
            _fail("route unit differs from its exact ownership partition")
    return result


@dataclass(frozen=True, slots=True)
class _ResolvedRoute:
    landing: ObservationRouteLandingV2
    route_receipt_ordinal: int
    route_landing_receipt_sha256: str
    units: tuple[ExpectedValueUnitV1, ...]
    fields: tuple[LandingFieldAuthorityV2, ...] | tuple[RouteFieldCanonicalAliasFieldV1, ...]
    alias: bool


@dataclass(frozen=True, slots=True)
class RawNbaApiRouteFieldLandingAuthorityReceiptV1:
    """Aggregate identity over one bundle's complete route-field landing join."""

    receipt_sha256: str
    raw_authority_bundle_sha256: str
    result_cell_authority_sha256: str
    lossless_ownership_receipt_sha256: str
    expected_unit_inventory_sha256: str
    expected_unit_count: int
    expected_unit_root_sha256: str
    representation_assignment_count: int
    representation_assignment_root_sha256: str
    selected_observation_count: int
    selected_observation_root_sha256: str
    raw_route_landing_count: int
    raw_route_landing_root_sha256: str
    direct_route_count: int
    route_receipt_count: int
    route_receipt_root_sha256: str
    alias_route_count: int
    alias_receipt_count: int
    alias_receipt_root_sha256: str
    field_binding_row_count: int
    route_only_row_count: int
    landing_field_count: int
    landing_field_root_sha256: str

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = _RECEIPT_KIND

    def __post_init__(self) -> None:
        for label, value in (
            ("route-field authority receipt", self.receipt_sha256),
            ("route-field raw authority bundle", self.raw_authority_bundle_sha256),
            ("route-field result-cell authority", self.result_cell_authority_sha256),
            ("route-field lossless ownership", self.lossless_ownership_receipt_sha256),
            ("route-field expected-unit inventory", self.expected_unit_inventory_sha256),
            ("route-field expected-unit root", self.expected_unit_root_sha256),
            ("route-field assignment root", self.representation_assignment_root_sha256),
            ("route-field selected-observation root", self.selected_observation_root_sha256),
            ("route-field Raw landing root", self.raw_route_landing_root_sha256),
            ("route-field route-receipt root", self.route_receipt_root_sha256),
            ("route-field alias-receipt root", self.alias_receipt_root_sha256),
            ("route-field row root", self.landing_field_root_sha256),
        ):
            _sha256(value, label=label)
        for label, value, maximum in (
            (
                "route-field expected-unit count",
                self.expected_unit_count,
                MAX_PUBLIC_VALUE_EXPECTED_UNITS,
            ),
            (
                "route-field assignment count",
                self.representation_assignment_count,
                MAX_PUBLIC_VALUE_EXPECTED_UNITS,
            ),
            (
                "route-field selected-observation count",
                self.selected_observation_count,
                MAX_AUTHORITY_ROWS,
            ),
            ("route-field Raw landing count", self.raw_route_landing_count, MAX_AUTHORITY_ROWS),
            (
                "route-field direct-route count",
                self.direct_route_count,
                MAX_ROUTE_FIELD_LANDING_RECEIPTS,
            ),
            (
                "route-field route-receipt count",
                self.route_receipt_count,
                MAX_ROUTE_FIELD_LANDING_RECEIPTS,
            ),
            (
                "route-field alias-route count",
                self.alias_route_count,
                MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES,
            ),
            (
                "route-field alias-receipt count",
                self.alias_receipt_count,
                MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES,
            ),
            (
                "route-field field-binding count",
                self.field_binding_row_count,
                MAX_ROUTE_FIELD_LANDING_ROWS,
            ),
            (
                "route-field route-only count",
                self.route_only_row_count,
                MAX_ROUTE_FIELD_LANDING_ROWS,
            ),
            ("route-field row count", self.landing_field_count, MAX_ROUTE_FIELD_LANDING_ROWS),
        ):
            _count(value, label=label, maximum=maximum)
        if (
            self.expected_unit_count != self.representation_assignment_count
            or self.direct_route_count != self.route_receipt_count
            or self.alias_route_count != self.alias_receipt_count
            or self.raw_route_landing_count != self.direct_route_count + self.alias_route_count
            or self.landing_field_count != self.field_binding_row_count + self.route_only_row_count
            or (self.expected_unit_count == 0) != (self.landing_field_count == 0)
        ):
            _fail("route-field authority aggregate denominators are inconsistent")
        zero_roots = {
            "representation_assignment_root_sha256": _ordered_root(
                kind=_ASSIGNMENT_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=(),
                maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS,
            ),
            "selected_observation_root_sha256": _ordered_root(
                kind=_SELECTED_OBSERVATION_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=(),
                maximum=MAX_AUTHORITY_ROWS,
            ),
            "raw_route_landing_root_sha256": _ordered_root(
                kind=_RAW_LANDING_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=(),
                maximum=MAX_AUTHORITY_ROWS,
            ),
            "route_receipt_root_sha256": _ordered_root(
                kind=_ROUTE_RECEIPT_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=(),
                maximum=MAX_ROUTE_FIELD_LANDING_RECEIPTS,
            ),
            "alias_receipt_root_sha256": _ordered_root(
                kind=_ALIAS_RECEIPT_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=(),
                maximum=MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES,
            ),
            "landing_field_root_sha256": _ordered_root(
                kind=_LANDING_FIELD_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=(),
                maximum=MAX_ROUTE_FIELD_LANDING_ROWS,
            ),
        }
        for count, root_name in (
            (self.representation_assignment_count, "representation_assignment_root_sha256"),
            (self.selected_observation_count, "selected_observation_root_sha256"),
            (self.raw_route_landing_count, "raw_route_landing_root_sha256"),
            (self.route_receipt_count, "route_receipt_root_sha256"),
            (self.alias_receipt_count, "alias_receipt_root_sha256"),
            (self.landing_field_count, "landing_field_root_sha256"),
        ):
            if (count == 0) != (getattr(self, root_name) == zero_roots[root_name]):
                _fail(f"route-field authority {root_name} zero proof is inconsistent")
        if self.receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("route-field authority receipt digest differs from its exact identity")

    @classmethod
    def build(cls, **values: object) -> Self:
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **values,
        }
        try:
            return cls(receipt_sha256=_canonical_sha256(payload), **cast("Any", values))
        except RouteFieldLandingBuilderError:
            raise
        except (TypeError, ValueError) as exc:
            raise RouteFieldLandingBuilderError(
                "route-field authority receipt builder received invalid fields"
            ) from exc

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "receipt_sha256"
            },
        }

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        if type(value) is not dict:
            _fail("route-field authority receipt row is not one exact mapping")
        row = cast("dict[object, object]", value)
        if any(type(key) is not str for key in row) or tuple(row) != (
            RAW_NBA_API_ROUTE_FIELD_LANDING_AUTHORITY_RECEIPT_COLUMNS
        ):
            _fail("route-field authority receipt row lacks exact ordered columns")
        if type(row["schema_version"]) is not int or row["schema_version"] != cls.schema_version:
            _fail("route-field authority receipt row has a foreign schema version")
        try:
            return cls(
                **cast(
                    "Any",
                    {item.name: row[item.name] for item in fields(cls)},
                )
            )
        except RouteFieldLandingBuilderError:
            raise
        except (TypeError, ValueError) as exc:
            raise RouteFieldLandingBuilderError(
                "route-field authority receipt row failed exact reconstruction"
            ) from exc

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row())


@dataclass(frozen=True, slots=True)
class RawNbaApiRouteFieldLandingAuthorityV1:
    """In-memory closure over one aggregate receipt and its exact public rows."""

    receipt: RawNbaApiRouteFieldLandingAuthorityReceiptV1
    rows: tuple[RawNbaApiRouteFieldLandingV1, ...]

    def __post_init__(self) -> None:
        if type(self.receipt) is not RawNbaApiRouteFieldLandingAuthorityReceiptV1:
            _fail("route-field authority has a foreign aggregate receipt")
        receipt = RawNbaApiRouteFieldLandingAuthorityReceiptV1.from_row(self.receipt.to_row())
        if type(self.rows) is not tuple or len(self.rows) != receipt.landing_field_count:
            _fail("route-field authority row denominator is mutable or incomplete")
        field_bindings = route_only = 0
        replayed: list[RawNbaApiRouteFieldLandingV1] = []
        for ordinal, item in enumerate(self.rows):
            if type(item) is not RawNbaApiRouteFieldLandingV1:
                _fail("route-field authority contains a foreign public row DTO")
            row = RawNbaApiRouteFieldLandingV1.from_row(item.to_row())
            if (
                row != item
                or row.landing_field_ordinal != ordinal
                or row.raw_authority_bundle_sha256 != receipt.raw_authority_bundle_sha256
            ):
                _fail("route-field authority rows are foreign, mutated, or reordered")
            field_bindings += row.row_kind == "field_binding"
            route_only += row.row_kind == "route_only"
            replayed.append(row)
        expected_root = _ordered_root(
            kind=_LANDING_FIELD_ROOT_KIND,
            raw_authority_bundle_sha256=receipt.raw_authority_bundle_sha256,
            item_sha256s=tuple(item.landing_field_sha256 for item in replayed),
            maximum=MAX_ROUTE_FIELD_LANDING_ROWS,
        )
        if (
            field_bindings != receipt.field_binding_row_count
            or route_only != receipt.route_only_row_count
            or expected_root != receipt.landing_field_root_sha256
        ):
            _fail("route-field authority rows differ from aggregate counts or root")


def _validate_raw_and_public_authorities(
    *,
    raw_authority_bundle: object,
    expected_unit_inventory: object,
    representation_assignments: object,
    result_cell_authority_receipt: object,
    lossless_ownership_authority: object,
) -> tuple[
    RawRequestAuthorityBundleV2,
    ExpectedValueUnitInventoryV1,
    tuple[ValueRepresentationAssignmentV1, ...],
    str,
    LosslessOwnershipAuthorityV1,
    tuple[RequestObservationV2, ...],
]:
    if type(raw_authority_bundle) is not RawRequestAuthorityBundleV2:
        _fail("route-field builder requires the exact Raw Authority V2 bundle")
    try:
        bundle = validate_raw_request_authority_bundle(raw_authority_bundle)
    except (TypeError, ValueError) as exc:
        raise RouteFieldLandingBuilderError("Raw Authority V2 bundle fails exact replay") from exc
    inventory = _exact_inventory(expected_unit_inventory)
    assignments = _exact_assignments(inventory, representation_assignments)
    ownership = _exact_ownership(lossless_ownership_authority)
    result_cell_sha256 = _result_cell_authority_sha256(
        result_cell_authority_receipt,
        raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    if (
        inventory.raw_authority_bundle_sha256 != bundle.bundle_sha256
        or ownership.receipt.raw_authority_bundle_sha256 != bundle.bundle_sha256
        or ownership.expected_unit_inventory != inventory
        or ownership.representation_assignments != assignments
    ):
        _fail("public value authorities disagree on their exact Raw bundle or unit closure")
    selected_by_sha: dict[str, RequestObservationV2] = {}
    for item in bundle.observations:
        if item.lifecycle != "selected_terminal":
            continue
        observation_sha256 = item.attempt.observation_sha256
        if observation_sha256 in selected_by_sha:
            _fail("selected Raw observation inventory contains a duplicate")
        selected_by_sha[observation_sha256] = item
    if len(selected_by_sha) != len(ownership.observations):
        _fail("ownership authority omits or fabricates a selected Raw observation")

    occurrences_by_observation: dict[str, dict[int, ResultOccurrenceV2]] = {}
    for occurrence in bundle.occurrences:
        by_ordinal = occurrences_by_observation.setdefault(
            occurrence.observation_sha256,
            {},
        )
        if occurrence.occurrence_ordinal in by_ordinal:
            _fail("Raw occurrence inventory duplicates one observation ordinal")
        by_ordinal[occurrence.occurrence_ordinal] = occurrence

    response_partition_by_observation: dict[str, LosslessOwnershipPartitionV1] = {}
    for partition in ownership.partitions:
        if partition.partition_kind not in {"response_residual", "response_fixed_zero"}:
            continue
        if partition.observation_sha256 in response_partition_by_observation:
            _fail("selected observation has duplicate response ownership partitions")
        response_partition_by_observation[partition.observation_sha256] = partition

    fixed_landings_by_observation: dict[str, list[ObservationRouteLandingV2]] = {}
    for landing in bundle.landings:
        if landing.landing_semantic == "response_fixed_zero":
            fixed_landings_by_observation.setdefault(landing.observation_sha256, []).append(landing)

    selected_rows: list[RequestObservationV2] = []
    prior_observation_key: _ObservationOrderKey | None = None
    unit_cursor = 0
    for observation_ordinal, owned_observation in enumerate(ownership.observations):
        observation_sha256 = owned_observation.observation_sha256
        raw_observation = selected_by_sha.pop(observation_sha256, None)
        if raw_observation is None:
            _fail("ownership observation is absent from selected Raw authority")
        observation_key = _observation_order_key(raw_observation)
        if prior_observation_key is not None and observation_key <= prior_observation_key:
            _fail("ownership observations are not in canonical Raw order")
        prior_observation_key = observation_key
        selected_rows.append(raw_observation)
        source_input_kind = _source_input_kind(raw_observation)
        if (
            owned_observation.observation_ordinal != observation_ordinal
            or owned_observation.observation_sha256 != observation_sha256
            or owned_observation.observation_record_sha256
            != raw_observation.observation_record_sha256
            or owned_observation.source_input_kind != source_input_kind
        ):
            _fail("ownership observation order or Raw identity differs")
        occurrence_index = occurrences_by_observation.get(observation_sha256, {})
        if set(occurrence_index) != set(range(len(occurrence_index))):
            _fail("Raw occurrence ordinals are not contiguous within one observation")
        occurrences = tuple(occurrence_index[ordinal] for ordinal in range(len(occurrence_index)))
        for occurrence in occurrences:
            if unit_cursor >= inventory.unit_count:
                _fail("expected-unit inventory omits a selected result occurrence")
            unit = inventory.units[unit_cursor]
            if (
                unit.unit_kind != "result_occurrence"
                or unit.observation_sha256 != observation_sha256
                or unit.observation_ordinal != observation_ordinal
                or unit.occurrence_sha256 != occurrence.occurrence_sha256
                or unit.occurrence_ordinal != occurrence.occurrence_ordinal
                or assignments[unit_cursor].source_input_kind != source_input_kind
            ):
                _fail("expected-unit occurrence denominator differs from Raw V2")
            unit_cursor += 1
        if (
            unit_cursor < inventory.unit_count
            and inventory.units[unit_cursor].observation_sha256 == observation_sha256
        ):
            unit = inventory.units[unit_cursor]
            if (
                unit.unit_kind not in {"response_residual", "response_fixed_zero"}
                or assignments[unit_cursor].source_input_kind != source_input_kind
            ):
                _fail("expected response unit has a foreign source-input binding")
            unit_cursor += 1
        response_partition = response_partition_by_observation.get(observation_sha256)
        if response_partition is None:
            _fail("selected observation lacks one exact response ownership partition")
        if response_partition.partition_kind == "response_fixed_zero":
            fixed = tuple(fixed_landings_by_observation.get(observation_sha256, ()))
            if (
                occurrences
                or len(fixed) != 1
                or response_partition.fixed_zero_landing_sha256 != fixed[0].landing_sha256
            ):
                _fail("fixed-zero ownership differs from Raw zero-response landing")
    if selected_by_sha:
        _fail("ownership authority leaves selected Raw observations unclaimed")
    if unit_cursor != inventory.unit_count:
        _fail("expected-unit inventory contains a foreign or reopened observation")
    return bundle, inventory, assignments, result_cell_sha256, ownership, tuple(selected_rows)


def build_raw_nba_api_route_field_landing_authority(
    *,
    raw_authority_bundle: RawRequestAuthorityBundleV2,
    expected_unit_inventory: ExpectedValueUnitInventoryV1,
    representation_assignments: tuple[ValueRepresentationAssignmentV1, ...],
    result_cell_authority_receipt: RawResultCellAuthorityReceiptV2,
    lossless_ownership_authority: LosslessOwnershipAuthorityV1,
    route_landing_receipts: tuple[RouteFieldLandingReceiptV2, ...],
    canonical_alias_receipts: tuple[RouteFieldCanonicalAliasReceiptV1, ...],
) -> RawNbaApiRouteFieldLandingAuthorityV1:
    """Build the exact bundle-local public route-field landing authority."""

    (
        bundle,
        inventory,
        assignments,
        result_cell_sha256,
        ownership,
        selected_observations,
    ) = _validate_raw_and_public_authorities(
        raw_authority_bundle=raw_authority_bundle,
        expected_unit_inventory=expected_unit_inventory,
        representation_assignments=representation_assignments,
        result_cell_authority_receipt=result_cell_authority_receipt,
        lossless_ownership_authority=lossless_ownership_authority,
    )
    if type(route_landing_receipts) is not tuple or len(route_landing_receipts) > (
        MAX_ROUTE_FIELD_LANDING_RECEIPTS
    ):
        _fail("route receipt inventory is mutable or over-bound")
    if type(canonical_alias_receipts) is not tuple or len(canonical_alias_receipts) > (
        MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES
    ):
        _fail("canonical-alias receipt inventory is mutable or over-bound")
    safe_receipts = tuple(
        _safe_route_receipt(
            item,
            raw_authority_bundle_sha256=bundle.bundle_sha256,
        )
        for item in route_landing_receipts
    )
    if len({item.receipt.landing_receipt_sha256 for item in safe_receipts}) != len(safe_receipts):
        _fail("route receipt inventory contains duplicate identities")
    observation_by_sha = {item.attempt.observation_sha256: item for item in selected_observations}
    landings_by_observation: dict[str, list[ObservationRouteLandingV2]] = {}
    for landing in bundle.landings:
        if landing.observation_sha256 not in observation_by_sha:
            _fail("Raw landing belongs to a non-selected observation")
        landings_by_observation.setdefault(landing.observation_sha256, []).append(landing)
    canonical_landing_rows: list[ObservationRouteLandingV2] = []
    for observation in selected_observations:
        observation_sha256 = observation.attempt.observation_sha256
        rows = landings_by_observation.pop(observation_sha256, [])
        if tuple(item.route_ordinal for item in rows) != tuple(range(len(rows))):
            _fail("Raw landing route ordinals are not contiguous in canonical observation order")
        canonical_landing_rows.extend(rows)
    if landings_by_observation:
        _fail("Raw landing inventory contains an orphan observation")
    canonical_landings = tuple(canonical_landing_rows)
    direct_landings = tuple(
        item for item in canonical_landings if item.landing_semantic != "response_canonical_alias"
    )
    alias_landings = tuple(
        item for item in canonical_landings if item.landing_semantic == "response_canonical_alias"
    )
    if len(direct_landings) != len(safe_receipts):
        _fail("direct Raw landing denominator differs from route receipts")
    safe_receipt_by_match_key: dict[tuple[object, ...], _SafeRouteReceipt] = {}
    for safe in safe_receipts:
        key = _safe_receipt_match_key(safe)
        if key in safe_receipt_by_match_key:
            _fail("one direct Raw landing is claimed by several route receipts")
        safe_receipt_by_match_key[key] = safe
    receipt_for_landing: dict[str, _SafeRouteReceipt] = {}
    for landing in direct_landings:
        observation = observation_by_sha[landing.observation_sha256]
        safe = safe_receipt_by_match_key.pop(
            _raw_landing_match_key(landing, observation),
            None,
        )
        if safe is None or not _receipt_matches_landing(safe, landing, observation):
            _fail("route receipt is absent, ambiguous, or foreign to direct Raw landings")
        receipt_for_landing[landing.landing_sha256] = safe
    if safe_receipt_by_match_key or len(receipt_for_landing) != len(direct_landings):
        _fail("one or more direct Raw landings lack a route receipt")

    occurrence_by_sha = {item.occurrence_sha256: item for item in bundle.occurrences}
    raw_occurrences_by_route: dict[tuple[str, str], list[ResultOccurrenceV2]] = {}
    for occurrence in bundle.occurrences:
        for route_id in occurrence.canonical_route_ids():
            raw_occurrences_by_route.setdefault(
                (occurrence.observation_sha256, route_id),
                [],
            ).append(occurrence)
    units_by_occurrence = {
        (item.observation_sha256, cast("str", item.occurrence_sha256)): item
        for item in inventory.units
        if item.unit_kind == "result_occurrence"
    }
    response_unit_by_observation = {
        item.observation_sha256: item
        for item in inventory.units
        if item.unit_kind != "result_occurrence"
    }
    response_partition_kind_by_observation = {
        item.observation_sha256: item.response_partition_kind for item in ownership.observations
    }
    assignments_by_unit = {
        item.unit_sha256: assignment
        for item, assignment in zip(inventory.units, assignments, strict=True)
    }
    partitions_by_unit = _unit_partition_index(ownership)
    resolved_direct: dict[str, _ResolvedRoute] = {}
    owned_units: dict[str, str] = {}
    canonical_receipt_sha256s: list[str] = []
    for route_receipt_ordinal, landing in enumerate(direct_landings):
        safe = receipt_for_landing[landing.landing_sha256]
        receipt = safe.receipt
        selected_sha256s = tuple(item.occurrence_sha256 for item in safe.selected_occurrences)
        raw_source_occurrences = tuple(
            raw_occurrences_by_route.get((landing.observation_sha256, landing.route_id), ())
        )
        if (
            selected_sha256s != tuple(item.occurrence_sha256 for item in raw_source_occurrences)
            or receipt.selected_occurrence_count != landing.source_occurrence_count
            or _canonical_sha256(list(selected_sha256s)) != landing.source_occurrences_sha256
        ):
            _fail("route receipt selected occurrences differ from Raw landing sources")
        for selected in safe.selected_occurrences:
            raw_occurrence = occurrence_by_sha.get(selected.occurrence_sha256)
            if raw_occurrence is None or not _selected_occurrence_matches_raw(
                selected,
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                observation=observation_by_sha[landing.observation_sha256],
                occurrence=raw_occurrence,
            ):
                _fail("route selected-occurrence summary differs from Raw occurrence")
        units = _units_for_receipt(
            safe=safe,
            landing=landing,
            units_by_occurrence=units_by_occurrence,
            response_unit_by_observation=response_unit_by_observation,
            response_partition_kind_by_observation=response_partition_kind_by_observation,
            assignments_by_unit=assignments_by_unit,
            partitions_by_unit=partitions_by_unit,
        )
        for unit in units:
            prior = owned_units.setdefault(unit.unit_sha256, landing.landing_sha256)
            if prior != landing.landing_sha256:
                _fail("one expected unit is owned by several direct route receipts")
        resolved_direct[landing.landing_sha256] = _ResolvedRoute(
            landing=landing,
            route_receipt_ordinal=route_receipt_ordinal,
            route_landing_receipt_sha256=receipt.landing_receipt_sha256,
            units=units,
            fields=safe.fields,
            alias=False,
        )
        canonical_receipt_sha256s.append(receipt.landing_receipt_sha256)
    if set(owned_units) != {item.unit_sha256 for item in inventory.units}:
        _fail("route receipts leave an expected unit unowned or claim a foreign unit")

    alias_receipt_by_landing: dict[str, RouteFieldCanonicalAliasReceiptV1] = {}
    if len(alias_landings) != len(canonical_alias_receipts):
        _fail("Raw alias landing denominator differs from canonical-alias receipts")
    alias_landing_by_sha = {item.landing_sha256: item for item in alias_landings}
    direct_landing_by_observation_route: dict[tuple[str, str], ObservationRouteLandingV2] = {}
    for landing in direct_landings:
        key = (landing.observation_sha256, landing.route_id)
        if key in direct_landing_by_observation_route:
            _fail("direct Raw landing route identity is ambiguous within one observation")
        direct_landing_by_observation_route[key] = landing
    for item in canonical_alias_receipts:
        if type(item) is not RouteFieldCanonicalAliasReceiptV1:
            _fail("canonical-alias receipt inventory contains a foreign DTO")
        try:
            replayed = RouteFieldCanonicalAliasReceiptV1.from_row(item.to_row())
        except (TypeError, ValueError) as exc:
            raise RouteFieldLandingBuilderError(
                "canonical-alias receipt fails exact row replay"
            ) from exc
        if replayed != item or replayed.raw_authority_bundle_sha256 != bundle.bundle_sha256:
            _fail("canonical-alias receipt is mutated or belongs to a foreign Raw bundle")
        alias_landing = alias_landing_by_sha.pop(
            replayed.alias_raw_route_landing_sha256,
            None,
        )
        if (
            alias_landing is None
            or replayed.alias_raw_route_landing_sha256 in alias_receipt_by_landing
        ):
            _fail("canonical-alias receipt is absent, duplicated, or foreign to Raw landings")
        target_landing = direct_landing_by_observation_route.get(
            (alias_landing.observation_sha256, cast("str", alias_landing.alias_target_route_id))
        )
        target_safe = (
            None
            if target_landing is None
            else receipt_for_landing.get(target_landing.landing_sha256)
        )
        if target_landing is None or target_safe is None:
            _fail("canonical alias target landing or route receipt is absent")
        try:
            replayed.validate_against(
                alias_landing=alias_landing,
                target_landings=(target_landing,),
                target_route_receipts=(target_safe.receipt,),
            )
        except (TypeError, ValueError) as exc:
            raise RouteFieldLandingBuilderError(
                "canonical-alias receipt differs from independent target replay"
            ) from exc
        alias_receipt_by_landing[alias_landing.landing_sha256] = replayed
    if alias_landing_by_sha or len(alias_receipt_by_landing) != len(alias_landings):
        _fail("one or more Raw alias landings lack a canonical-alias receipt")

    resolved_routes: list[_ResolvedRoute] = []
    alias_receipt_sha256s: list[str] = []
    for landing in canonical_landings:
        direct = resolved_direct.get(landing.landing_sha256)
        if direct is not None:
            resolved_routes.append(direct)
            continue
        alias_receipt = alias_receipt_by_landing[landing.landing_sha256]
        target = resolved_direct.get(alias_receipt.target_raw_route_landing_sha256)
        if target is None:
            _fail("canonical alias targets a landing without direct unit ownership")
        if (
            alias_receipt.target_route_landing_receipt_sha256 != target.route_landing_receipt_sha256
            or alias_receipt.target_observation_sha256 != landing.observation_sha256
        ):
            _fail("canonical alias target receipt or observation drifted")
        resolved_routes.append(
            _ResolvedRoute(
                landing=landing,
                route_receipt_ordinal=target.route_receipt_ordinal,
                route_landing_receipt_sha256=target.route_landing_receipt_sha256,
                units=target.units,
                fields=alias_receipt.fields,
                alias=True,
            )
        )
        alias_receipt_sha256s.append(alias_receipt.receipt_sha256)

    predicted_rows = 0
    for route in resolved_routes:
        field_denominator = max(1, len(route.fields))
        contribution = _checked_product(
            len(route.units),
            field_denominator,
            maximum=MAX_ROUTE_FIELD_LANDING_ROWS,
            label="route-field row allocation",
        )
        predicted_rows = _checked_add(
            predicted_rows,
            contribution,
            maximum=MAX_ROUTE_FIELD_LANDING_ROWS,
            label="route-field row allocation",
        )

    rows: list[RawNbaApiRouteFieldLandingV1] = []
    field_binding_count = route_only_count = 0
    for route in resolved_routes:
        landing = route.landing
        for unit in route.units:
            assignment = assignments_by_unit[unit.unit_sha256]
            if not route.fields:
                rows.append(
                    RawNbaApiRouteFieldLandingV1.build(
                        landing_field_ordinal=len(rows),
                        route_receipt_ordinal=route.route_receipt_ordinal,
                        raw_authority_bundle_sha256=bundle.bundle_sha256,
                        route_landing_receipt_sha256=route.route_landing_receipt_sha256,
                        raw_route_landing_sha256=landing.landing_sha256,
                        observation_sha256=landing.observation_sha256,
                        route_ordinal=landing.route_ordinal,
                        route_id=landing.route_id,
                        staging_key=landing.staging_key,
                        unit_sha256=unit.unit_sha256,
                        unit_ordinal=unit.unit_ordinal,
                        unit_kind=unit.unit_kind,
                        occurrence_sha256=unit.occurrence_sha256,
                        occurrence_ordinal=unit.occurrence_ordinal,
                        assignment_sha256=assignment.assignment_sha256,
                        source_input_kind=assignment.source_input_kind,
                        representation_kind=assignment.representation_kind,
                        row_kind="route_only",
                        field_ordinal=None,
                        field_name=None,
                        field_authority_sha256=None,
                        field_origin=None,
                        logical_type_sha256=None,
                    )
                )
                route_only_count += 1
                continue
            for field in route.fields:
                if route.alias:
                    alias_field = cast("RouteFieldCanonicalAliasFieldV1", field)
                    field_ordinal = alias_field.field_ordinal
                    field_name = alias_field.field_name
                    field_authority_sha256 = alias_field.target_field_authority_sha256
                    field_origin = alias_field.field_origin
                    logical_type_sha256 = alias_field.logical_type_sha256
                else:
                    direct_field = cast("LandingFieldAuthorityV2", field)
                    field_ordinal = direct_field.storage_ordinal
                    field_name = direct_field.storage_column
                    field_authority_sha256 = direct_field.authority_sha256
                    field_origin = direct_field.origin
                    logical_type_sha256 = direct_field.logical_type_sha256
                rows.append(
                    RawNbaApiRouteFieldLandingV1.build(
                        landing_field_ordinal=len(rows),
                        route_receipt_ordinal=route.route_receipt_ordinal,
                        raw_authority_bundle_sha256=bundle.bundle_sha256,
                        route_landing_receipt_sha256=route.route_landing_receipt_sha256,
                        raw_route_landing_sha256=landing.landing_sha256,
                        observation_sha256=landing.observation_sha256,
                        route_ordinal=landing.route_ordinal,
                        route_id=landing.route_id,
                        staging_key=landing.staging_key,
                        unit_sha256=unit.unit_sha256,
                        unit_ordinal=unit.unit_ordinal,
                        unit_kind=unit.unit_kind,
                        occurrence_sha256=unit.occurrence_sha256,
                        occurrence_ordinal=unit.occurrence_ordinal,
                        assignment_sha256=assignment.assignment_sha256,
                        source_input_kind=assignment.source_input_kind,
                        representation_kind=assignment.representation_kind,
                        row_kind="field_binding",
                        field_ordinal=field_ordinal,
                        field_name=field_name,
                        field_authority_sha256=field_authority_sha256,
                        field_origin=field_origin,
                        logical_type_sha256=logical_type_sha256,
                    )
                )
                field_binding_count += 1
    if len(rows) != predicted_rows:
        _fail("route-field row allocation differs from its exact preflight")
    exact_rows = tuple(rows)
    assignment_root = _ordered_root(
        kind=_ASSIGNMENT_ROOT_KIND,
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        item_sha256s=tuple(item.assignment_sha256 for item in assignments),
        maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    )
    observation_root = _ordered_root(
        kind=_SELECTED_OBSERVATION_ROOT_KIND,
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        item_sha256s=tuple(item.observation_record_sha256 for item in selected_observations),
        maximum=MAX_AUTHORITY_ROWS,
    )
    raw_landing_root = _ordered_root(
        kind=_RAW_LANDING_ROOT_KIND,
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        item_sha256s=tuple(item.landing_sha256 for item in canonical_landings),
        maximum=MAX_AUTHORITY_ROWS,
    )
    route_receipt_root = _ordered_root(
        kind=_ROUTE_RECEIPT_ROOT_KIND,
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        item_sha256s=tuple(canonical_receipt_sha256s),
        maximum=MAX_ROUTE_FIELD_LANDING_RECEIPTS,
    )
    alias_receipt_root = _ordered_root(
        kind=_ALIAS_RECEIPT_ROOT_KIND,
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        item_sha256s=tuple(alias_receipt_sha256s),
        maximum=MAX_ROUTE_FIELD_CANONICAL_ALIAS_CANDIDATES,
    )
    row_root = _ordered_root(
        kind=_LANDING_FIELD_ROOT_KIND,
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        item_sha256s=tuple(item.landing_field_sha256 for item in exact_rows),
        maximum=MAX_ROUTE_FIELD_LANDING_ROWS,
    )
    receipt = RawNbaApiRouteFieldLandingAuthorityReceiptV1.build(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        result_cell_authority_sha256=result_cell_sha256,
        lossless_ownership_receipt_sha256=ownership.receipt.receipt_sha256,
        expected_unit_inventory_sha256=inventory.inventory_sha256,
        expected_unit_count=inventory.unit_count,
        expected_unit_root_sha256=inventory.unit_root_sha256,
        representation_assignment_count=len(assignments),
        representation_assignment_root_sha256=assignment_root,
        selected_observation_count=len(selected_observations),
        selected_observation_root_sha256=observation_root,
        raw_route_landing_count=len(canonical_landings),
        raw_route_landing_root_sha256=raw_landing_root,
        direct_route_count=len(direct_landings),
        route_receipt_count=len(safe_receipts),
        route_receipt_root_sha256=route_receipt_root,
        alias_route_count=len(alias_landings),
        alias_receipt_count=len(alias_receipt_sha256s),
        alias_receipt_root_sha256=alias_receipt_root,
        field_binding_row_count=field_binding_count,
        route_only_row_count=route_only_count,
        landing_field_count=len(exact_rows),
        landing_field_root_sha256=row_root,
    )
    return RawNbaApiRouteFieldLandingAuthorityV1(receipt=receipt, rows=exact_rows)
