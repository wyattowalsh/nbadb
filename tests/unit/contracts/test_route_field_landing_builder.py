from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from nbadb.contracts import route_field_landing_builder as builder_module
from nbadb.contracts import typed_field_value_receipt as typed_receipt_module
from nbadb.contracts.canonical_arrow_value import ArrowLogicalTypeV1
from nbadb.contracts.lossless_ownership import (
    LosslessObservationOwnershipV1,
    LosslessOwnershipBindingV1,
    LosslessOwnershipPartitionV1,
    build_lossless_ownership_authority,
)
from nbadb.contracts.public_value_types import (
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.raw_result_cell_authority import RawResultCellAuthorityReceiptV2
from nbadb.contracts.route_field_canonical_alias import (
    RouteFieldCanonicalAliasReceiptV1,
)
from nbadb.contracts.route_field_landing_authority import (
    RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS,
)
from nbadb.contracts.route_field_landing_builder import (
    RAW_NBA_API_ROUTE_FIELD_LANDING_AUTHORITY_RECEIPT_COLUMNS,
    RawNbaApiRouteFieldLandingAuthorityReceiptV1,
    RawNbaApiRouteFieldLandingAuthorityV1,
    RouteFieldLandingBuilderError,
    build_raw_nba_api_route_field_landing_authority,
)
from nbadb.contracts.typed_field_value_receipt import (
    LandingFieldAuthorityV2,
    RouteFieldLandingReceiptV2,
    SourceOccurrenceAuthorityV2,
    canonical_sha256,
)
from tests.unit.contracts.test_public_value_authority_adapter import _live_bundle
from tests.unit.contracts.test_raw_request_authority import (
    _static_bundle,
    _stats_fallback_bundle,
    _strict_stats_bundle,
    _video_bundle,
)

if TYPE_CHECKING:
    from nbadb.contracts.raw_request_authority import (
        ObservationRouteLandingV2,
        RawRequestAuthorityBundleV2,
        RequestObservationV2,
        ResultOccurrenceV2,
    )


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class _Bomb:
    def __getattribute__(self, name: str) -> Any:
        if name in {"__class__", "__repr__"}:
            return object.__getattribute__(self, name)
        raise AssertionError(f"forbidden child access: {name}")

    def __iter__(self) -> Any:
        raise AssertionError("forbidden child iteration")

    def __len__(self) -> int:
        raise AssertionError("forbidden child length")

    def __bool__(self) -> bool:
        raise AssertionError("forbidden child truthiness")


def _field(
    *,
    landing: ObservationRouteLandingV2,
    ordinal: int = 0,
    name: str = "public_value",
) -> LandingFieldAuthorityV2:
    logical_type = ArrowLogicalTypeV1(type_kind="utf8", offset_width=32)
    values: dict[str, object] = {
        "field_fate_structure_sha256": _sha("field-fate"),
        "route_id": landing.route_id,
        "staging_key": landing.staging_key,
        "storage_ordinal": ordinal,
        "storage_column": name,
        "origin": "storage_only",
        "sink_sha256": _sha(f"sink:{landing.route_id}:{ordinal}"),
        "route_binding_sha256s": (),
        "source_occurrence_sha256s": (),
        "source_endpoint_ids": (),
        "source_result_set_names": (),
        "source_result_set_ordinals": (),
        "source_header_ordinals": (),
        "source_field_names": (),
        "lossless_binding_sha256s": (),
        "logical_type": logical_type,
        "logical_type_sha256": logical_type.type_sha256,
    }
    identity = {
        "schema_version": 2,
        "kind": LandingFieldAuthorityV2.kind,
        **{key: value for key, value in values.items() if key not in {"logical_type"}},
        "logical_type": logical_type.to_dict(),
    }
    return LandingFieldAuthorityV2(
        **cast("Any", values),
        authority_sha256=canonical_sha256(identity),
    )


def _source_occurrence(
    bundle: RawRequestAuthorityBundleV2,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
) -> SourceOccurrenceAuthorityV2:
    return typed_receipt_module._source_occurrence_authority(
        bundle=bundle,
        observation=observation,
        occurrence=occurrence,
    )


def _route_receipt(
    *,
    bundle: RawRequestAuthorityBundleV2,
    landing: ObservationRouteLandingV2,
    source_shape: str,
    fields: tuple[LandingFieldAuthorityV2, ...],
) -> RouteFieldLandingReceiptV2:
    observation = next(
        item
        for item in bundle.observations
        if item.attempt.observation_sha256 == landing.observation_sha256
    )
    occurrences = tuple(
        item
        for item in bundle.occurrences
        if item.observation_sha256 == landing.observation_sha256
        and landing.route_id in item.canonical_route_ids()
    )
    selected = tuple(
        _source_occurrence(bundle, observation, occurrence) for occurrence in occurrences
    )
    receipt = object.__new__(RouteFieldLandingReceiptV2)
    field_count = len(fields)
    cell_count = landing.persisted_row_count * field_count
    conditional = source_shape not in {"result_occurrence_bound", "response_fixed_zero"}
    decoder_by_family = {
        "stats": "stats_result_set_rows_v1",
        "live": "live_record_projection_v1",
        "static": "static_dataset_records_v1",
    }
    conditional_decoder_by_shape = {
        "selected_result_bound": "conditional_selected_result_rows_v2",
        "body_node_bound": "conditional_body_node_rows_v2",
        "hybrid_result_body_bound": "conditional_hybrid_result_body_rows_v2",
        "live_lossless_bound": "conditional_live_lossless_rows_v2",
        "response_fixed_zero": "response_fixed_zero_v2",
    }
    decoder_kind = (
        decoder_by_family[observation.attempt.source_family]
        if source_shape == "result_occurrence_bound"
        else conditional_decoder_by_shape[source_shape]
    )
    values: dict[str, object] = {
        "canonical_frame_format": landing.canonical_frame_format,
        "frame_content_hash_contract": landing.frame_content_hash_contract,
        "frame_schema_hash_contract": landing.frame_schema_hash_contract,
        "readback_receipt_sha256": _sha(f"readback:{landing.landing_sha256}"),
        "receipt_root_sha256": landing.receipt_root_sha256,
        "raw_bundle_sha256": bundle.bundle_sha256,
        "field_fate_structure_sha256": _sha("field-fate"),
        "route_id": landing.route_id,
        "staging_key": landing.staging_key,
        "source_family": observation.attempt.source_family,
        "decoder_kind": decoder_kind,
        "source_shape": source_shape,
        "endpoint_id": observation.attempt.endpoint_id,
        "conditional_authority_sha256": _sha("conditional") if conditional else None,
        "row_partition_receipt_sha256": _sha(f"partition:{landing.landing_sha256}"),
        "row_count": landing.persisted_row_count,
        "occurrence_partition_count": (
            len(selected) if source_shape == "result_occurrence_bound" else 0
        ),
        "selected_occurrence_count": len(selected),
        "field_count": field_count,
        "cell_count": cell_count,
        "source_verified_cell_count": 0,
        "storage_readback_only_cell_count": cell_count,
        "field_authorities": fields,
        "selected_occurrence_authorities": selected,
        "selected_occurrence_sha256s": tuple(item.occurrence_sha256 for item in selected),
        "row_slice_receipt_sha256s": tuple(
            _sha(f"slice:{landing.landing_sha256}:{ordinal}")
            for ordinal in range(
                len(selected)
                if source_shape == "result_occurrence_bound"
                else 0
                if source_shape == "response_fixed_zero"
                else landing.persisted_row_count
            )
        ),
        "value_node_count": 0,
        "value_max_depth": 0,
        "value_utf8_bytes": 0,
        "value_binary_bytes": 0,
        "value_container_items": 0,
        "value_canonical_bytes": 0,
        "fields_sha256": canonical_sha256([item.to_dict() for item in fields]),
        "occurrences_sha256": canonical_sha256([]),
        "selected_occurrences_sha256": canonical_sha256([item.to_dict() for item in selected]),
        "values_sha256": canonical_sha256([]),
        "conditional_rows_sha256": canonical_sha256([]),
    }
    for name, value in values.items():
        object.__setattr__(receipt, name, value)
    # The production join must never inspect these value-bearing children.
    object.__setattr__(receipt, "occurrence_authorities", _Bomb())
    object.__setattr__(receipt, "value_receipts", _Bomb())
    object.__setattr__(receipt, "conditional_row_receipts", _Bomb())
    object.__setattr__(
        receipt,
        "landing_receipt_sha256",
        canonical_sha256(receipt.identity_payload()),
    )
    return receipt


def _result_cell_receipt(bundle_sha256: str) -> RawResultCellAuthorityReceiptV2:
    receipt = object.__new__(RawResultCellAuthorityReceiptV2)
    proof_sha256 = _sha("result-cell-proof")
    authority_sha256 = _canonical_sha256(
        {
            "schema_version": RawResultCellAuthorityReceiptV2.schema_version,
            "kind": RawResultCellAuthorityReceiptV2.kind,
            "raw_authority_bundle_sha256": bundle_sha256,
            "public_table_proof_sha256": proof_sha256,
        }
    )
    object.__setattr__(receipt, "authority_sha256", authority_sha256)
    object.__setattr__(receipt, "raw_authority_bundle_sha256", bundle_sha256)
    object.__setattr__(receipt, "public_table_proof_sha256", proof_sha256)
    object.__setattr__(receipt, "public_table_proof", _Bomb())
    return receipt


def _observation_order_key(observation: RequestObservationV2) -> tuple[object, ...]:
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


def _public_authorities(
    bundle: RawRequestAuthorityBundleV2,
    *,
    result_representation: str = "rectangular_result_cells_v1",
) -> tuple[
    ExpectedValueUnitInventoryV1,
    tuple[ValueRepresentationAssignmentV1, ...],
    Any,
]:
    units: list[ExpectedValueUnitV1] = []
    assignments: list[ValueRepresentationAssignmentV1] = []
    observations: list[LosslessObservationOwnershipV1] = []
    partitions: list[LosslessOwnershipPartitionV1] = []
    bindings: list[LosslessOwnershipBindingV1] = []
    selected = tuple(
        sorted(
            (item for item in bundle.observations if item.lifecycle == "selected_terminal"),
            key=_observation_order_key,
        )
    )
    for observation_ordinal, observation in enumerate(selected):
        observation_sha256 = observation.attempt.observation_sha256
        source_input_kind = (
            "parser_input_body"
            if observation.body_disposition == "public_parser_input"
            else "declared_bodyless_packet"
        )
        observation_partitions: list[LosslessOwnershipPartitionV1] = []
        observation_bindings: list[LosslessOwnershipBindingV1] = []
        occurrences = tuple(
            sorted(
                (
                    item
                    for item in bundle.occurrences
                    if item.observation_sha256 == observation_sha256
                ),
                key=lambda item: item.occurrence_ordinal,
            )
        )
        for occurrence in occurrences:
            unit = ExpectedValueUnitV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                unit_ordinal=len(units),
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                unit_kind="result_occurrence",
                occurrence_sha256=occurrence.occurrence_sha256,
                occurrence_ordinal=occurrence.occurrence_ordinal,
            )
            assignment = ValueRepresentationAssignmentV1.build(
                expected_unit=unit,
                source_input_kind=source_input_kind,
                representation_kind=cast("Any", result_representation),
            )
            partition = LosslessOwnershipPartitionV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                observation_record_sha256=observation.observation_record_sha256,
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                partition_ordinal=len(partitions),
                observation_partition_ordinal=len(observation_partitions),
                partition_kind="result_occurrence",
                bindings=(),
                expected_unit=unit,
                assignment=assignment,
            )
            units.append(unit)
            assignments.append(assignment)
            partitions.append(partition)
            observation_partitions.append(partition)

        fixed_landings = tuple(
            item
            for item in bundle.landings
            if item.observation_sha256 == observation_sha256
            and item.landing_semantic == "response_fixed_zero"
        )
        conditional_landings = tuple(
            item
            for item in bundle.landings
            if item.observation_sha256 == observation_sha256
            and item.landing_semantic == "conditional_lossless"
        )
        response_unit: ExpectedValueUnitV1 | None = None
        response_assignment: ValueRepresentationAssignmentV1 | None = None
        fixed_landing_sha256: str | None = None
        response_bindings: tuple[LosslessOwnershipBindingV1, ...] = ()
        if conditional_landings:
            response_kind = "response_residual"
            representation = "response_lossless_records_v1"
        elif not occurrences and len(fixed_landings) == 1:
            response_kind = "response_fixed_zero"
            representation = "response_fixed_zero_v1"
            fixed_landing_sha256 = fixed_landings[0].landing_sha256
        else:
            response_kind = "response_residual"
            representation = None
        if representation is not None:
            response_unit = ExpectedValueUnitV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                unit_ordinal=len(units),
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                unit_kind=cast("Any", response_kind),
            )
            response_assignment = ValueRepresentationAssignmentV1.build(
                expected_unit=response_unit,
                source_input_kind=source_input_kind,
                representation_kind=cast("Any", representation),
            )
            units.append(response_unit)
            assignments.append(response_assignment)
            if response_kind == "response_residual":
                binding = LosslessOwnershipBindingV1.build(
                    raw_authority_bundle_sha256=bundle.bundle_sha256,
                    observation_record_sha256=observation.observation_record_sha256,
                    observation_sha256=observation_sha256,
                    observation_ordinal=observation_ordinal,
                    binding_ordinal=len(bindings),
                    observation_record_ordinal=0,
                    partition_ordinal=len(partitions),
                    source_record_sha256=_sha(f"source-record:{observation_sha256}"),
                    expected_unit=response_unit,
                    assignment=response_assignment,
                )
                bindings.append(binding)
                observation_bindings.append(binding)
                response_bindings = (binding,)
        response_partition = LosslessOwnershipPartitionV1.build(
            raw_authority_bundle_sha256=bundle.bundle_sha256,
            observation_record_sha256=observation.observation_record_sha256,
            observation_sha256=observation_sha256,
            observation_ordinal=observation_ordinal,
            partition_ordinal=len(partitions),
            observation_partition_ordinal=len(observation_partitions),
            partition_kind=cast("Any", response_kind),
            bindings=response_bindings,
            expected_unit=response_unit,
            assignment=response_assignment,
            fixed_zero_landing_sha256=fixed_landing_sha256,
        )
        partitions.append(response_partition)
        observation_partitions.append(response_partition)
        observations.append(
            LosslessObservationOwnershipV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                observation_record_sha256=observation.observation_record_sha256,
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                source_input_kind=source_input_kind,
                partitions=tuple(observation_partitions),
                bindings=tuple(observation_bindings),
            )
        )
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        units=tuple(units),
    )
    authority = build_lossless_ownership_authority(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_unit_inventory=inventory,
        representation_assignments=tuple(assignments),
        observations=tuple(observations),
        partitions=tuple(partitions),
        bindings=tuple(bindings),
    )
    return inventory, tuple(assignments), authority


def _route_receipts(
    bundle: RawRequestAuthorityBundleV2,
    *,
    zero_fields: bool = False,
) -> tuple[RouteFieldLandingReceiptV2, ...]:
    observation_by_sha256 = {item.attempt.observation_sha256: item for item in bundle.observations}
    receipts: list[RouteFieldLandingReceiptV2] = []
    for landing in bundle.landings:
        if landing.landing_semantic == "response_canonical_alias":
            continue
        if landing.landing_semantic == "occurrence_bound":
            source_shape = "result_occurrence_bound"
        elif landing.landing_semantic == "response_fixed_zero":
            source_shape = "response_fixed_zero"
        elif observation_by_sha256[landing.observation_sha256].attempt.source_family == "live":
            source_shape = "live_lossless_bound"
        else:
            source_shape = (
                "hybrid_result_body_bound" if landing.source_occurrence_count else "body_node_bound"
            )
        fields = () if zero_fields else (_field(landing=landing),)
        receipts.append(
            _route_receipt(
                bundle=bundle,
                landing=landing,
                source_shape=source_shape,
                fields=fields,
            )
        )
    return tuple(receipts)


def _alias_receipts(
    bundle: RawRequestAuthorityBundleV2,
    route_receipts: tuple[RouteFieldLandingReceiptV2, ...],
) -> tuple[RouteFieldCanonicalAliasReceiptV1, ...]:
    direct_landings = tuple(
        item for item in bundle.landings if item.landing_semantic != "response_canonical_alias"
    )
    return tuple(
        RouteFieldCanonicalAliasReceiptV1.build(
            raw_authority_bundle_sha256=bundle.bundle_sha256,
            alias_landing=landing,
            target_landings=direct_landings,
            target_route_receipts=route_receipts,
        )
        for landing in bundle.landings
        if landing.landing_semantic == "response_canonical_alias"
    )


def _build_case(
    bundle: RawRequestAuthorityBundleV2,
    *,
    zero_fields: bool = False,
    result_representation: str = "rectangular_result_cells_v1",
    route_receipts: tuple[RouteFieldLandingReceiptV2, ...] | None = None,
    alias_receipts: tuple[RouteFieldCanonicalAliasReceiptV1, ...] | None = None,
) -> RawNbaApiRouteFieldLandingAuthorityV1:
    inventory, assignments, ownership = _public_authorities(
        bundle,
        result_representation=result_representation,
    )
    receipts = (
        _route_receipts(bundle, zero_fields=zero_fields)
        if route_receipts is None
        else route_receipts
    )
    aliases = _alias_receipts(bundle, receipts) if alias_receipts is None else alias_receipts
    return build_raw_nba_api_route_field_landing_authority(
        raw_authority_bundle=bundle,
        expected_unit_inventory=inventory,
        representation_assignments=assignments,
        result_cell_authority_receipt=_result_cell_receipt(bundle.bundle_sha256),
        lossless_ownership_authority=ownership,
        route_landing_receipts=receipts,
        canonical_alias_receipts=aliases,
    )


def test_strict_stats_rows_are_complete_ordered_and_value_free() -> None:
    bundle = _strict_stats_bundle()
    authority = _build_case(bundle)

    assert authority.receipt.expected_unit_count == len(bundle.occurrences)
    assert authority.receipt.direct_route_count == len(bundle.landings)
    assert authority.receipt.alias_route_count == 0
    assert authority.receipt.field_binding_row_count == len(bundle.occurrences)
    assert authority.receipt.route_only_row_count == 0
    assert len(authority.rows) == len(bundle.occurrences)
    assert [item.landing_field_ordinal for item in authority.rows] == list(
        range(len(authority.rows))
    )
    assert [item.route_receipt_ordinal for item in authority.rows] == list(
        range(len(authority.rows))
    )
    assert [item.unit_ordinal for item in authority.rows] == list(range(len(authority.rows)))
    assert all(item.representation_kind == "rectangular_result_cells_v1" for item in authority.rows)
    assert all(
        tuple(item.to_row()) == RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS for item in authority.rows
    )
    assert (
        RawNbaApiRouteFieldLandingAuthorityReceiptV1.from_row(authority.receipt.to_row())
        == authority.receipt
    )
    assert tuple(authority.receipt.to_row()) == (
        RAW_NBA_API_ROUTE_FIELD_LANDING_AUTHORITY_RECEIPT_COLUMNS
    )
    assert (
        RawNbaApiRouteFieldLandingAuthorityV1(
            receipt=authority.receipt,
            rows=authority.rows,
        )
        == authority
    )


def test_static_occurrence_receipt_preserves_its_family_decoder() -> None:
    bundle, _observation, _occurrence, _landing = _static_bundle()
    receipts = _route_receipts(bundle)

    assert len(receipts) == 1
    assert receipts[0].source_family == "static"
    assert receipts[0].source_shape == "result_occurrence_bound"
    assert receipts[0].decoder_kind == "static_dataset_records_v1"

    authority = _build_case(bundle, route_receipts=receipts)
    assert authority.receipt.expected_unit_count == 1
    assert {item.representation_kind for item in authority.rows} == {"rectangular_result_cells_v1"}


def test_missing_stats_wide_routes_are_exact_nonowners_of_lossless_units() -> None:
    bundle, _observation, occurrences, landings = _stats_fallback_bundle("missing_result")
    receipts = _route_receipts(bundle)

    assert [item.decoder_kind for item in receipts] == [
        "stats_result_set_rows_v1",
        "stats_result_set_rows_v1",
        "conditional_hybrid_result_body_rows_v2",
    ]
    authority = _build_case(
        bundle,
        result_representation="stats_lossless_records_v1",
        route_receipts=receipts,
    )

    occurrence_landings = {
        item.landing_sha256 for item in landings if item.landing_semantic == "occurrence_bound"
    }
    conditional_landing = next(
        item for item in landings if item.landing_semantic == "conditional_lossless"
    )
    expected_unit_count = len(occurrences) + 1
    assert authority.receipt.raw_route_landing_count == len(landings)
    assert authority.receipt.route_receipt_count == len(receipts)
    assert authority.receipt.expected_unit_count == expected_unit_count
    assert len(authority.rows) == expected_unit_count
    assert len({item.unit_sha256 for item in authority.rows}) == expected_unit_count
    assert not (occurrence_landings & {item.raw_route_landing_sha256 for item in authority.rows})
    assert {item.raw_route_landing_sha256 for item in authority.rows} == {
        conditional_landing.landing_sha256
    }
    assert {item.representation_kind for item in authority.rows} == {
        "stats_lossless_records_v1",
        "response_lossless_records_v1",
    }


def test_live_wide_route_is_an_exact_nonowner_of_live_lossless_units() -> None:
    bundle = _live_bundle()
    receipts = _route_receipts(bundle)

    assert [item.source_shape for item in receipts] == [
        "result_occurrence_bound",
        "live_lossless_bound",
    ]
    assert [item.decoder_kind for item in receipts] == [
        "live_record_projection_v1",
        "conditional_live_lossless_rows_v2",
    ]
    authority = _build_case(
        bundle,
        result_representation="live_lossless_nodes_v1",
        route_receipts=receipts,
    )

    occurrence_landing = next(
        item for item in bundle.landings if item.landing_semantic == "occurrence_bound"
    )
    conditional_landing = next(
        item for item in bundle.landings if item.landing_semantic == "conditional_lossless"
    )
    expected_unit_count = len(bundle.occurrences) + 1
    assert authority.receipt.raw_route_landing_count == len(bundle.landings)
    assert authority.receipt.route_receipt_count == len(receipts)
    assert authority.receipt.expected_unit_count == expected_unit_count
    assert len(authority.rows) == expected_unit_count
    assert len({item.unit_sha256 for item in authority.rows}) == expected_unit_count
    assert all(
        item.raw_route_landing_sha256 != occurrence_landing.landing_sha256
        for item in authority.rows
    )
    assert {item.raw_route_landing_sha256 for item in authority.rows} == {
        conditional_landing.landing_sha256
    }
    assert {item.representation_kind for item in authority.rows} == {
        "live_lossless_nodes_v1",
        "response_lossless_records_v1",
    }


def test_zero_field_fixed_zero_emits_one_route_only_sentinel() -> None:
    bundle, _observation, occurrences, landings = _video_bundle("VideoEvents", {})
    assert occurrences == ()
    assert len(landings) == 1 and landings[0].landing_semantic == "response_fixed_zero"

    authority = _build_case(bundle, zero_fields=True)

    assert authority.receipt.expected_unit_count == 1
    assert authority.receipt.field_binding_row_count == 0
    assert authority.receipt.route_only_row_count == 1
    assert len(authority.rows) == 1
    row = authority.rows[0]
    assert row.unit_kind == "response_fixed_zero"
    assert row.representation_kind == "response_fixed_zero_v1"
    assert row.row_kind == "route_only"
    assert row.field_ordinal is row.field_name is row.field_authority_sha256 is None


def test_video_details_drift_keeps_nonowning_fixed_route_and_residual_owner() -> None:
    bundle, _observation, occurrences, landings = _video_bundle(
        "VideoDetails",
        {"future": {"x": 1}},
    )
    assert occurrences == ()
    assert [item.landing_semantic for item in landings] == [
        "response_fixed_zero",
        "conditional_lossless",
    ]

    authority = _build_case(bundle)

    assert authority.receipt.expected_unit_count == 1
    assert authority.receipt.direct_route_count == 2
    assert authority.receipt.route_receipt_count == 2
    assert authority.receipt.field_binding_row_count == 1
    assert authority.receipt.route_only_row_count == 0
    assert len(authority.rows) == 1
    row = authority.rows[0]
    assert row.landing_field_ordinal == 0
    assert row.route_receipt_ordinal == 1
    assert row.raw_route_landing_sha256 == landings[1].landing_sha256
    assert row.route_ordinal == landings[1].route_ordinal == 1
    assert row.unit_kind == "response_residual"
    assert row.representation_kind == "response_lossless_records_v1"
    assert row.row_kind == "field_binding"


def test_alias_mirrors_target_unit_and_fields_without_dual_ownership() -> None:
    bundle, _observation, occurrences, landings = _video_bundle(
        "VideoEvents",
        {"future": {"x": [1, "two"]}},
    )
    assert occurrences == ()
    assert [item.landing_semantic for item in landings] == [
        "response_canonical_alias",
        "conditional_lossless",
    ]

    authority = _build_case(bundle)

    assert authority.receipt.expected_unit_count == 1
    assert authority.receipt.direct_route_count == 1
    assert authority.receipt.alias_route_count == 1
    assert len(authority.rows) == 2
    alias_row, target_row = authority.rows
    assert alias_row.raw_route_landing_sha256 == landings[0].landing_sha256
    assert target_row.raw_route_landing_sha256 == landings[1].landing_sha256
    assert alias_row.unit_sha256 == target_row.unit_sha256
    assert alias_row.assignment_sha256 == target_row.assignment_sha256
    assert alias_row.route_receipt_ordinal == target_row.route_receipt_ordinal == 0
    assert alias_row.route_landing_receipt_sha256 == target_row.route_landing_receipt_sha256
    assert alias_row.field_authority_sha256 == target_row.field_authority_sha256


def test_input_order_does_not_change_rows_or_roots() -> None:
    bundle = _strict_stats_bundle()
    receipts = _route_receipts(bundle)
    first = _build_case(bundle, route_receipts=receipts)
    second = _build_case(bundle, route_receipts=tuple(reversed(receipts)))

    assert second == first
    assert second.receipt.receipt_sha256 == first.receipt.receipt_sha256
    assert second.receipt.landing_field_root_sha256 == first.receipt.landing_field_root_sha256


def test_bomb_children_are_not_touched() -> None:
    bundle = _strict_stats_bundle()
    receipts = _route_receipts(bundle)

    authority = _build_case(bundle, route_receipts=receipts)

    assert authority.rows


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"decoder_kind": "static_dataset_records_v1"}, "decoder relabels"),
        ({"row_slice_receipt_sha256s": ()}, "slice denominator"),
        ({"value_max_depth": builder_module.MAX_JSON_DEPTH + 1}, "value depth"),
        ({"field_fate_structure_sha256": _sha("forged-field-fate")}, "field authority"),
        ({"canonical_frame_format": "forged-frame-v1"}, "foreign to direct Raw landings"),
    ],
)
def test_route_receipt_scalar_reseals_fail_external_pin_and_bound_checks(
    changes: dict[str, object],
    message: str,
) -> None:
    bundle = _strict_stats_bundle()
    receipts = _route_receipts(bundle)
    forged = object.__new__(RouteFieldLandingReceiptV2)
    for item in fields(RouteFieldLandingReceiptV2):
        object.__setattr__(
            forged, item.name, changes.get(item.name, getattr(receipts[0], item.name))
        )
    object.__setattr__(
        forged,
        "landing_receipt_sha256",
        canonical_sha256(forged.identity_payload()),
    )

    with pytest.raises(RouteFieldLandingBuilderError, match=message):
        _build_case(bundle, route_receipts=(forged, *receipts[1:]))


def test_overflow_is_rejected_before_public_row_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _strict_stats_bundle()
    monkeypatch.setattr(builder_module, "MAX_ROUTE_FIELD_LANDING_ROWS", 1)

    with pytest.raises(RouteFieldLandingBuilderError, match="allocation"):
        _build_case(bundle)


def test_sparse_inventory_and_representation_gap_fail_closed() -> None:
    bundle = _strict_stats_bundle()
    inventory, assignments, ownership = _public_authorities(
        bundle,
        result_representation="stats_lossless_records_v1",
    )
    receipts = _route_receipts(bundle)

    with pytest.raises(RouteFieldLandingBuilderError, match="leave an expected unit unowned"):
        build_raw_nba_api_route_field_landing_authority(
            raw_authority_bundle=bundle,
            expected_unit_inventory=inventory,
            representation_assignments=assignments,
            result_cell_authority_receipt=_result_cell_receipt(bundle.bundle_sha256),
            lossless_ownership_authority=ownership,
            route_landing_receipts=receipts,
            canonical_alias_receipts=(),
        )

    missing_bundle, *_rest = _stats_fallback_bundle("missing_result")
    missing_inventory, live_assignments, live_ownership = _public_authorities(
        missing_bundle,
        result_representation="live_lossless_nodes_v1",
    )
    missing_receipts = _route_receipts(missing_bundle)
    with pytest.raises(RouteFieldLandingBuilderError, match="source shape conflicts"):
        build_raw_nba_api_route_field_landing_authority(
            raw_authority_bundle=missing_bundle,
            expected_unit_inventory=missing_inventory,
            representation_assignments=live_assignments,
            result_cell_authority_receipt=_result_cell_receipt(missing_bundle.bundle_sha256),
            lossless_ownership_authority=live_ownership,
            route_landing_receipts=missing_receipts,
            canonical_alias_receipts=(),
        )

    sparse_inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        units=inventory.units[:-1],
    )
    sparse_assignments = assignments[:-1]
    sparse_response = LosslessOwnershipPartitionV1.build(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        observation_record_sha256=ownership.observations[0].observation_record_sha256,
        observation_sha256=ownership.observations[0].observation_sha256,
        observation_ordinal=0,
        partition_ordinal=1,
        observation_partition_ordinal=1,
        partition_kind="response_residual",
        bindings=(),
    )
    sparse_partitions = (ownership.partitions[0], sparse_response)
    sparse_observation = LosslessObservationOwnershipV1.build(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        observation_record_sha256=ownership.observations[0].observation_record_sha256,
        observation_sha256=ownership.observations[0].observation_sha256,
        observation_ordinal=0,
        source_input_kind="parser_input_body",
        partitions=sparse_partitions,
        bindings=(),
    )
    sparse_ownership = build_lossless_ownership_authority(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_unit_inventory=sparse_inventory,
        representation_assignments=sparse_assignments,
        observations=(sparse_observation,),
        partitions=sparse_partitions,
        bindings=(),
    )
    with pytest.raises(RouteFieldLandingBuilderError, match="omits a selected result occurrence"):
        build_raw_nba_api_route_field_landing_authority(
            raw_authority_bundle=bundle,
            expected_unit_inventory=sparse_inventory,
            representation_assignments=sparse_assignments,
            result_cell_authority_receipt=_result_cell_receipt(bundle.bundle_sha256),
            lossless_ownership_authority=sparse_ownership,
            route_landing_receipts=receipts,
            canonical_alias_receipts=(),
        )


def test_route_overlap_and_alias_drift_fail_closed() -> None:
    stats_bundle = _strict_stats_bundle()
    receipts = _route_receipts(stats_bundle)
    overlapping_receipt = object.__new__(RouteFieldLandingReceiptV2)
    for item in fields(RouteFieldLandingReceiptV2):
        object.__setattr__(overlapping_receipt, item.name, getattr(receipts[0], item.name))
    object.__setattr__(overlapping_receipt, "readback_receipt_sha256", _sha("other-readback"))
    object.__setattr__(
        overlapping_receipt,
        "landing_receipt_sha256",
        canonical_sha256(overlapping_receipt.identity_payload()),
    )
    with pytest.raises(RouteFieldLandingBuilderError, match="claimed by several"):
        _build_case(stats_bundle, route_receipts=(receipts[0], overlapping_receipt))

    alias_bundle, _observation, _occurrences, _landings = _video_bundle(
        "VideoEvents",
        {"future": {"x": [1, "two"]}},
    )
    alias_route_receipts = _route_receipts(alias_bundle)
    aliases = _alias_receipts(alias_bundle, alias_route_receipts)
    drifted = object.__new__(RouteFieldCanonicalAliasReceiptV1)
    for item in fields(RouteFieldCanonicalAliasReceiptV1):
        object.__setattr__(drifted, item.name, getattr(aliases[0], item.name))
    object.__setattr__(
        drifted,
        "target_route_landing_receipt_sha256",
        _sha("drifted-target"),
    )
    object.__setattr__(drifted, "receipt_sha256", _canonical_sha256(drifted.identity_payload()))
    with pytest.raises(RouteFieldLandingBuilderError, match="row replay"):
        _build_case(
            alias_bundle,
            route_receipts=alias_route_receipts,
            alias_receipts=(drifted,),
        )


def test_authority_row_reseal_and_reorder_fail_closed() -> None:
    authority = _build_case(_strict_stats_bundle())
    rows = list(authority.rows)
    row = rows[0]
    mutated = row.to_row()
    mutated["raw_route_landing_sha256"] = _sha("foreign-landing")
    identity = {
        "kind": "raw_nba_api_route_field_landing_v1",
        **{key: value for key, value in mutated.items() if key != "landing_field_sha256"},
    }
    mutated["landing_field_sha256"] = _canonical_sha256(identity)
    rows[0] = type(row).from_row(mutated)
    with pytest.raises(RouteFieldLandingBuilderError, match="root"):
        RawNbaApiRouteFieldLandingAuthorityV1(
            receipt=authority.receipt,
            rows=tuple(rows),
        )
    with pytest.raises(RouteFieldLandingBuilderError, match="reordered"):
        RawNbaApiRouteFieldLandingAuthorityV1(
            receipt=authority.receipt,
            rows=tuple(reversed(authority.rows)),
        )


def test_builder_ast_forbids_value_children_and_layer_imports() -> None:
    source_path = Path(builder_module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_attributes = {
        "value_receipts",
        "conditional_row_receipts",
        "occurrence_authorities",
    }
    assert not {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes
    }
    forbidden_import_fragments = {
        "independent_stats_value_decoder",
        "independent_live_value_decoder",
        "extract",
        "staging",
        "orchestrate",
        "polars",
        "pyarrow",
    }
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not {
        module
        for module in imported_modules
        if any(fragment in module for fragment in forbidden_import_fragments)
    }
    forbidden_imported_names = {
        "TypedFieldValueReceiptV2",
        "ConditionalRowValueReceiptV2",
    }
    assert not {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in forbidden_imported_names
    }


def test_w2_route_replay_path_has_no_sort_or_nested_full_inventory_scan() -> None:
    tree = ast.parse(Path(builder_module.__file__).read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in {
            "_validate_raw_and_public_authorities",
            "_units_for_receipt",
            "build_raw_nba_api_route_field_landing_authority",
        }
    }
    assert set(functions) == {
        "_validate_raw_and_public_authorities",
        "_units_for_receipt",
        "build_raw_nba_api_route_field_landing_authority",
    }
    assert not any(
        (isinstance(call.func, ast.Name) and call.func.id == "sorted")
        or (isinstance(call.func, ast.Attribute) and call.func.attr == "sort")
        for function in functions.values()
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
    )

    forbidden_names = {"direct_landings", "alias_landings", "route_landing_receipts"}
    forbidden_attributes = {
        ("bundle", "occurrences"),
        ("bundle", "landings"),
        ("ownership", "partitions"),
    }
    for function in functions.values():
        for outer_loop in (node for node in ast.walk(function) if isinstance(node, ast.For)):
            nested_comprehensions = (
                child
                for statement in outer_loop.body
                for child in ast.walk(statement)
                if isinstance(child, ast.comprehension)
            )
            for comprehension in nested_comprehensions:
                iterator = comprehension.iter
                assert not (isinstance(iterator, ast.Name) and iterator.id in forbidden_names)
                assert not (
                    isinstance(iterator, ast.Attribute)
                    and isinstance(iterator.value, ast.Name)
                    and (iterator.value.id, iterator.attr) in forbidden_attributes
                )
