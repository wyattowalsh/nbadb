from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from nbadb.contracts import public_value_authority_adapter as adapter_module
from nbadb.contracts.live_lossless_value_authority import (
    LiveLosslessValueAuthorityV1,
    build_live_lossless_value_authority,
)
from nbadb.contracts.public_value_authority_adapter import (
    PublicValueAuthorityAdapterError,
    build_public_value_ownership_authority,
)
from nbadb.contracts.raw_request_authority import (
    RawRequestAuthorityBundleV2,
    RawRequestAuthorityError,
    RequestObservationV2,
    ResultOccurrenceV2,
)
from nbadb.contracts.raw_result_cell_authority import (
    RawNbaApiResultCellV2,
    RawResultCellAuthorityReceiptV2,
    validate_raw_result_cell_authority,
)
from nbadb.contracts.stats_lossless_value_authority import (
    StatsLosslessRecordV1,
    StatsLosslessResultV1,
    build_stats_lossless_value_authority,
    canonical_sha256,
    stats_lossless_result_declaration_value,
)
from tests.unit.contracts.test_raw_request_authority import _video_bundle
from tests.unit.contracts.test_raw_request_finalization import (
    _case,
    finalize_raw_request_capture,
)
from tests.unit.contracts.test_raw_result_cell_authority import (
    _canonical_cells,
    _combined_case,
    _stats_case,
    _wide_plus_lossless_case,
)

if TYPE_CHECKING:
    from nbadb.contracts.stats_lossless_value_authority import StatsLosslessValueAuthorityV1


def _union_bundles(
    *bundles: RawRequestAuthorityBundleV2,
) -> RawRequestAuthorityBundleV2:
    objects = {item.object_sha256: item for bundle in bundles for item in bundle.objects}
    return RawRequestAuthorityBundleV2.build(
        objects=tuple(objects.values()),
        observations=tuple(item for bundle in bundles for item in bundle.observations),
        occurrences=tuple(item for bundle in bundles for item in bundle.occurrences),
        landings=tuple(
            sorted(
                (item for bundle in bundles for item in bundle.landings),
                key=lambda item: (item.observation_sha256, item.route_ordinal),
            )
        ),
    )


def _live_bundle() -> RawRequestAuthorityBundleV2:
    snapshot, binding, receipts = _case("live")
    return finalize_raw_request_capture(snapshot, binding, receipts)


def _stats_authority(
    bundle: RawRequestAuthorityBundleV2,
    observation: RequestObservationV2,
    *,
    include_response_residual: bool = False,
) -> StatsLosslessValueAuthorityV1:
    occurrences = tuple(
        sorted(
            (
                item
                for item in bundle.occurrences
                if item.observation_sha256 == observation.attempt.observation_sha256
            ),
            key=lambda item: item.occurrence_ordinal,
        )
    )
    landings = tuple(
        item
        for item in bundle.landings
        if item.observation_sha256 == observation.attempt.observation_sha256
        and item.landing_semantic == "conditional_lossless"
    )
    assert len(landings) == 1
    landing = landings[0]
    parser_inputs = tuple(
        item for item in bundle.objects if item.object_sha256 == observation.body_object_sha256
    )
    assert len(parser_inputs) == 1
    parser_input = parser_inputs[0]
    inferred_expected_ordinals = {
        item.occurrence_sha256: ordinal
        for ordinal, item in enumerate(
            item
            for item in occurrences
            if observation.attempt.endpoint_id == "FranchiseHistory"
            and item.result_name != "Additive"
        )
    }
    expected_ordinal_by_occurrence = {
        item.occurrence_sha256: (
            item.canonical_result_ordinal
            if item.canonical_result_ordinal is not None
            else inferred_expected_ordinals.get(item.occurrence_sha256)
        )
        for item in occurrences
    }
    expected_headers_by_occurrence = {
        item.occurrence_sha256: (
            list(item.ordered_headers())
            if expected_ordinal_by_occurrence[item.occurrence_sha256] is not None
            else None
        )
        for item in occurrences
    }
    anomaly_by_occurrence = {
        item.occurrence_sha256: (
            ("removed_header",) if expected_headers_by_occurrence[item.occurrence_sha256] else ()
        )
        for item in occurrences
    }
    global_anomalies = tuple(
        sorted(
            {
                "unknown_dynamic_response",
                *(code for codes in anomaly_by_occurrence.values() for code in codes),
            }
        )
    )
    response_mode_sha256 = "d" * 64
    canonical_payload_sha256 = (
        canonical_sha256(7) if include_response_residual else parser_input.response_sha256
    )
    records: list[StatsLosslessRecordV1] = []
    results: list[StatsLosslessResultV1] = []
    provider_name_counts = {
        name: sum(item.result_name == name for item in occurrences)
        for name in {item.result_name for item in occurrences}
    }

    def record(
        *,
        occurrence: ResultOccurrenceV2 | None,
        global_record_ordinal: int,
        occurrence_record_ordinal: int | None,
        response_record_ordinal: int | None,
        record_kind: str,
        value_present: bool = False,
        value: object = None,
        node_ordinal: int | None = None,
        json_path: str | None = None,
        depth: int | None = None,
    ) -> StatsLosslessRecordV1:
        expected_ordinal = (
            None
            if occurrence is None
            else expected_ordinal_by_occurrence[occurrence.occurrence_sha256]
        )
        canonical_ordinal = (
            expected_ordinal
            if occurrence is not None
            and expected_ordinal is not None
            and provider_name_counts[occurrence.result_name] == 1
            else None
        )
        return StatsLosslessRecordV1.build(
            raw_authority_bundle_sha256=bundle.bundle_sha256,
            observation_record_sha256=observation.observation_record_sha256,
            observation_sha256=observation.attempt.observation_sha256,
            owner_kind=("response_residual" if occurrence is None else "result_occurrence"),
            occurrence_sha256=(None if occurrence is None else occurrence.occurrence_sha256),
            route_id=landing.route_id,
            route_authority_sha256=landing.route_authority_sha256,
            committed_receipt_sha256=landing.receipt_root_sha256,
            response_receipt_sha256=observation.capture_response_receipt_sha256,
            provider_authority_sha256=observation.attempt.provider_authority_sha256,
            endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
            response_mode_authority_sha256=response_mode_sha256,
            parser_input_sha256=parser_input.response_sha256,
            canonical_payload_sha256=canonical_payload_sha256,
            parameters_sha256=observation.attempt.safe_parameters_sha256,
            endpoint_id=observation.attempt.endpoint_id,
            endpoint_slug=observation.attempt.endpoint_id,
            response_state="unknown_result_envelope",
            legacy_envelope_name=None,
            global_record_ordinal=global_record_ordinal,
            occurrence_record_ordinal=occurrence_record_ordinal,
            response_record_ordinal=response_record_ordinal,
            record_kind=record_kind,  # type: ignore[arg-type]
            result_set_name=(None if occurrence is None else occurrence.result_name),
            result_set_occurrence=(
                None if occurrence is None else occurrence.duplicate_name_ordinal
            ),
            provider_result_ordinal=(
                None if occurrence is None else occurrence.provider_result_ordinal
            ),
            expected_result_ordinal=expected_ordinal,
            canonical_result_ordinal=canonical_ordinal,
            node_ordinal=node_ordinal,
            json_path=json_path,
            depth=depth,
            value_present=value_present,
            value=value,
            global_anomaly_codes=global_anomalies,
        )

    for result_ordinal, occurrence in enumerate(occurrences):
        expected_headers = expected_headers_by_occurrence[occurrence.occurrence_sha256]
        anomalies = anomaly_by_occurrence[occurrence.occurrence_sha256]
        normalized_output_sha256 = canonical_sha256(
            {"headers": [], "rows": [], "anomalies": list(anomalies)}
        )
        declaration = stats_lossless_result_declaration_value(
            presence="present_empty",
            expected_headers=expected_headers,
            anomaly_codes=anomalies,
            normalized_output_sha256=normalized_output_sha256,
            header_record_count=0,
            raw_row_occurrence_count=0,
            sequence_row_count=0,
            raw_cell_count=0,
        )
        first_global_ordinal = len(records)
        result_records = tuple(
            record(
                occurrence=occurrence,
                global_record_ordinal=first_global_ordinal + local_ordinal,
                occurrence_record_ordinal=local_ordinal,
                response_record_ordinal=None,
                record_kind=kind,
                value_present=True,
                value=value,
            )
            for local_ordinal, (kind, value) in enumerate(
                (("result_set", declaration), ("raw_headers", []), ("raw_rows", []))
            )
        )
        records.extend(result_records)
        expected_ordinal = expected_ordinal_by_occurrence[occurrence.occurrence_sha256]
        canonical_ordinal = (
            expected_ordinal
            if expected_ordinal is not None and provider_name_counts[occurrence.result_name] == 1
            else None
        )
        results.append(
            StatsLosslessResultV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                observation_record_sha256=observation.observation_record_sha256,
                observation_sha256=observation.attempt.observation_sha256,
                occurrence_sha256=occurrence.occurrence_sha256,
                route_id=landing.route_id,
                route_authority_sha256=landing.route_authority_sha256,
                committed_receipt_sha256=landing.receipt_root_sha256,
                response_receipt_sha256=observation.capture_response_receipt_sha256,
                result_ordinal=result_ordinal,
                result_set_name=occurrence.result_name,
                result_set_occurrence=occurrence.duplicate_name_ordinal,
                provider_result_ordinal=occurrence.provider_result_ordinal,
                expected_result_ordinal=expected_ordinal,
                canonical_result_ordinal=canonical_ordinal,
                occurrence_canonical_result_ordinal=None,
                presence="present_empty",
                expected_headers=expected_headers,
                raw_headers=[],
                raw_rows=[],
                header_record_count=0,
                raw_row_occurrence_count=0,
                sequence_row_count=0,
                raw_cell_count=0,
                anomaly_codes=anomalies,
                normalized_output_sha256=normalized_output_sha256,
                first_global_record_ordinal=first_global_ordinal,
                records=result_records,
            )
        )

    if include_response_residual:
        response_start = len(records)
        records.extend(
            (
                record(
                    occurrence=None,
                    global_record_ordinal=response_start,
                    occurrence_record_ordinal=None,
                    response_record_ordinal=0,
                    record_kind="response",
                ),
                record(
                    occurrence=None,
                    global_record_ordinal=response_start + 1,
                    occurrence_record_ordinal=None,
                    response_record_ordinal=1,
                    record_kind="json_node",
                    node_ordinal=0,
                    json_path="$",
                    depth=0,
                    value_present=True,
                    value=7,
                ),
            )
        )

    provider_count = len([item for item in occurrences if item.provider_result_ordinal is not None])
    expected_ordinals = {
        item for item in expected_ordinal_by_occurrence.values() if item is not None
    }
    return build_stats_lossless_value_authority(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        observation_record_sha256=observation.observation_record_sha256,
        observation_sha256=observation.attempt.observation_sha256,
        route_id=landing.route_id,
        route_authority_sha256=landing.route_authority_sha256,
        committed_receipt_sha256=landing.receipt_root_sha256,
        response_receipt_sha256=observation.capture_response_receipt_sha256,
        endpoint_id=observation.attempt.endpoint_id,
        endpoint_slug=observation.attempt.endpoint_id,
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
        endpoint_contract_sha256=observation.attempt.endpoint_contract_sha256,
        parameters_sha256=observation.attempt.safe_parameters_sha256,
        global_anomaly_codes=global_anomalies,
        provider_result_set_count=provider_count,
        expected_result_set_count=len(expected_ordinals),
        results=results,
        records=records,
    )


def _empty_live_authority(
    bundle: RawRequestAuthorityBundleV2,
) -> LiveLosslessValueAuthorityV1:
    return build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )


def _build(
    bundle: RawRequestAuthorityBundleV2,
    cells: tuple[RawNbaApiResultCellV2, ...],
    *,
    stats: tuple[StatsLosslessValueAuthorityV1, ...] = (),
    live: LiveLosslessValueAuthorityV1 | None = None,
):
    result_cells = validate_raw_result_cell_authority(bundle, cells)
    live_authority = _empty_live_authority(bundle) if live is None else live
    return build_public_value_ownership_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        result_cell_authority_receipt=result_cells,
        expected_result_cell_authority_sha256=result_cells.authority_sha256,
        stats_lossless_authorities=stats,
        expected_stats_lossless_authority_sha256s=tuple(
            item.receipt.authority_sha256 for item in stats
        ),
        live_lossless_authority=live_authority,
        expected_live_lossless_authority_receipt_sha256=(live_authority.receipt.receipt_sha256),
    )


def test_wide_stats_and_bodyless_static_build_one_bundle_scoped_authority() -> None:
    bundle, cells = _combined_case()
    authority = _build(bundle, cells)

    expected_observation_ids = tuple(
        item.attempt.observation_sha256
        for item in sorted(
            bundle.observations,
            key=lambda item: (
                item.attempt.logical_invocation_sha256,
                item.attempt.semantic_request_sha256,
                item.attempt.provider_call_ordinal,
                0 if item.attempt.page_ordinal is None else 1,
                0 if item.attempt.page_ordinal is None else item.attempt.page_ordinal,
                item.attempt.provider_call_role,
                item.attempt.provider_call_sha256,
                item.attempt.retry_ordinal,
                item.attempt.request_ordinal,
                item.attempt.observation_sha256,
            ),
        )
    )
    assert tuple(item.observation_sha256 for item in authority.observations) == (
        expected_observation_ids
    )
    assert authority.expected_unit_inventory.raw_authority_bundle_sha256 == (bundle.bundle_sha256)
    assert tuple(item.unit_ordinal for item in authority.expected_unit_inventory.units) == tuple(
        range(authority.expected_unit_inventory.unit_count)
    )
    assert {item.representation_kind for item in authority.representation_assignments} == {
        "rectangular_result_cells_v1"
    }
    assert {item.source_input_kind for item in authority.representation_assignments} == {
        "parser_input_body",
        "declared_bodyless_packet",
    }
    assert authority.receipt.source_record_count == len(cells)
    assert {item.source_record_sha256 for item in authority.bindings} == {
        item.cell_sha256 for item in cells
    }
    assert authority.receipt.zero_response_residual_partition_count == len(bundle.observations)


def test_input_observation_tuple_order_does_not_control_semantic_order() -> None:
    bundle, cells = _combined_case()
    reversed_bundle = RawRequestAuthorityBundleV2.build(
        objects=bundle.objects,
        observations=tuple(reversed(bundle.observations)),
        occurrences=bundle.occurrences,
        landings=bundle.landings,
    )
    reversed_cells = validate_raw_result_cell_authority(reversed_bundle, cells)
    reversed_live = _empty_live_authority(reversed_bundle)
    authority = build_public_value_ownership_authority(
        reversed_bundle,
        expected_raw_authority_bundle_sha256=reversed_bundle.bundle_sha256,
        result_cell_authority_receipt=reversed_cells,
        expected_result_cell_authority_sha256=reversed_cells.authority_sha256,
        stats_lossless_authorities=(),
        expected_stats_lossless_authority_sha256s=(),
        live_lossless_authority=reversed_live,
        expected_live_lossless_authority_receipt_sha256=(reversed_live.receipt.receipt_sha256),
    )
    assert tuple(item.observation_ordinal for item in authority.observations) == tuple(
        range(len(authority.observations))
    )
    expected = tuple(
        item.attempt.observation_sha256
        for item in sorted(
            reversed_bundle.observations,
            key=lambda item: (
                item.attempt.logical_invocation_sha256,
                item.attempt.semantic_request_sha256,
                item.attempt.provider_call_ordinal,
                0 if item.attempt.page_ordinal is None else 1,
                0 if item.attempt.page_ordinal is None else item.attempt.page_ordinal,
                item.attempt.provider_call_role,
                item.attempt.provider_call_sha256,
                item.attempt.retry_ordinal,
                item.attempt.request_ordinal,
                item.attempt.observation_sha256,
            ),
        )
    )
    assert tuple(item.observation_sha256 for item in authority.observations) == expected


def test_pin_validation_precedes_outer_type_and_member_traversal() -> None:
    with pytest.raises(
        PublicValueAuthorityAdapterError,
        match="expected Raw Authority bundle",
    ):
        build_public_value_ownership_authority(
            object(),
            expected_raw_authority_bundle_sha256="not-a-pin",
            result_cell_authority_receipt=object(),
            expected_result_cell_authority_sha256="also-not-a-pin",
            stats_lossless_authorities=object(),
            expected_stats_lossless_authority_sha256s=(),
            live_lossless_authority=object(),
            expected_live_lossless_authority_receipt_sha256="still-not-a-pin",
        )


def test_complete_terminal_selection_is_an_explicit_preallocation_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    result_cells = validate_raw_result_cell_authority(bundle, cells)
    live = _empty_live_authority(bundle)

    def reject_incomplete(_bundle: RawRequestAuthorityBundleV2) -> None:
        raise RawRequestAuthorityError("without a terminal selection")

    monkeypatch.setattr(
        RawRequestAuthorityBundleV2,
        "require_complete_terminal_selection",
        reject_incomplete,
    )
    with pytest.raises(PublicValueAuthorityAdapterError, match="canonical replay"):
        build_public_value_ownership_authority(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            result_cell_authority_receipt=result_cells,
            expected_result_cell_authority_sha256=result_cells.authority_sha256,
            stats_lossless_authorities=(),
            expected_stats_lossless_authority_sha256s=(),
            live_lossless_authority=live,
            expected_live_lossless_authority_receipt_sha256=live.receipt.receipt_sha256,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "raw_pin",
        "result_cell_pin",
        "live_pin",
        "stats_not_tuple",
        "result_cell_subclass",
    ],
)
def test_foreign_pins_and_outer_types_fail_closed(mutation: str) -> None:
    bundle, cells = _stats_case()
    result_cells = validate_raw_result_cell_authority(bundle, cells)
    live = _empty_live_authority(bundle)
    raw_pin = bundle.bundle_sha256
    result_pin = result_cells.authority_sha256
    live_pin = live.receipt.receipt_sha256
    stats: object = ()
    receipt: object = result_cells
    if mutation == "raw_pin":
        raw_pin = "0" * 64
    elif mutation == "result_cell_pin":
        result_pin = "0" * 64
    elif mutation == "live_pin":
        live_pin = "0" * 64
    elif mutation == "stats_not_tuple":
        stats = []
    else:

        class ReceiptSubclass(RawResultCellAuthorityReceiptV2):
            pass

        receipt = ReceiptSubclass(
            authority_sha256=result_cells.authority_sha256,
            raw_authority_bundle_sha256=result_cells.raw_authority_bundle_sha256,
            public_table_proof_sha256=result_cells.public_table_proof_sha256,
            public_table_proof=result_cells.public_table_proof,
        )
    with pytest.raises(PublicValueAuthorityAdapterError):
        build_public_value_ownership_authority(
            bundle,
            expected_raw_authority_bundle_sha256=raw_pin,
            result_cell_authority_receipt=receipt,
            expected_result_cell_authority_sha256=result_pin,
            stats_lossless_authorities=stats,
            expected_stats_lossless_authority_sha256s=(),
            live_lossless_authority=live,
            expected_live_lossless_authority_receipt_sha256=live_pin,
        )


def test_cross_bundle_empty_live_authority_is_rejected() -> None:
    bundle, cells = _combined_case()
    other_bundle, _other_cells = _stats_case()
    result_cells = validate_raw_result_cell_authority(bundle, cells)
    foreign_live = _empty_live_authority(other_bundle)
    with pytest.raises(PublicValueAuthorityAdapterError, match="live-lossless"):
        build_public_value_ownership_authority(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            result_cell_authority_receipt=result_cells,
            expected_result_cell_authority_sha256=result_cells.authority_sha256,
            stats_lossless_authorities=(),
            expected_stats_lossless_authority_sha256s=(),
            live_lossless_authority=foreign_live,
            expected_live_lossless_authority_receipt_sha256=(foreign_live.receipt.receipt_sha256),
        )


def test_coordinated_result_cell_receipt_reseal_cannot_cross_bundle() -> None:
    bundle, cells = _combined_case()
    other_bundle, other_cells = _stats_case()
    forged = validate_raw_result_cell_authority(other_bundle, other_cells)
    live = _empty_live_authority(bundle)
    with pytest.raises(PublicValueAuthorityAdapterError):
        build_public_value_ownership_authority(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            result_cell_authority_receipt=forged,
            expected_result_cell_authority_sha256=forged.authority_sha256,
            stats_lossless_authorities=(),
            expected_stats_lossless_authority_sha256s=(),
            live_lossless_authority=live,
            expected_live_lossless_authority_receipt_sha256=(live.receipt.receipt_sha256),
        )


def test_two_stats_authorities_restart_local_zero_but_central_units_do_not() -> None:
    first_bundle, first_observation, _first_occurrences, _first_landings = _video_bundle(
        "VideoDetails",
        {"resultSets": [{"name": "First", "headers": [], "rowSet": []}]},
    )
    second_bundle, second_observation, _second_occurrences, _second_landings = _video_bundle(
        "VideoEvents",
        {"resultSets": [{"name": "Second", "headers": [], "rowSet": []}]},
    )
    bundle = _union_bundles(first_bundle, second_bundle)
    stats_by_observation = {
        first_observation.attempt.observation_sha256: _stats_authority(
            bundle,
            first_observation,
            include_response_residual=True,
        ),
        second_observation.attempt.observation_sha256: _stats_authority(
            bundle,
            second_observation,
            include_response_residual=True,
        ),
    }
    observation_order = tuple(
        item.attempt.observation_sha256
        for item in sorted(
            bundle.observations,
            key=lambda item: (
                item.attempt.logical_invocation_sha256,
                item.attempt.semantic_request_sha256,
                item.attempt.provider_call_ordinal,
                0 if item.attempt.page_ordinal is None else 1,
                0 if item.attempt.page_ordinal is None else item.attempt.page_ordinal,
                item.attempt.provider_call_role,
                item.attempt.provider_call_sha256,
                item.attempt.retry_ordinal,
                item.attempt.request_ordinal,
                item.attempt.observation_sha256,
            ),
        )
        if item.attempt.observation_sha256 in stats_by_observation
    )
    stats = tuple(stats_by_observation[item] for item in observation_order)
    authority = _build(bundle, (), stats=stats)

    assert [item.expected_unit_inventory.units[0].unit_ordinal for item in stats] == [0, 0]
    assert tuple(item.unit_ordinal for item in authority.expected_unit_inventory.units) == tuple(
        range(authority.expected_unit_inventory.unit_count)
    )
    assert tuple(item.binding_ordinal for item in authority.bindings) == tuple(
        range(len(authority.bindings))
    )
    assert {item.representation_kind for item in authority.representation_assignments} == {
        "stats_lossless_records_v1",
        "response_lossless_records_v1",
    }

    result_cells = validate_raw_result_cell_authority(bundle, ())
    live = _empty_live_authority(bundle)
    permuted = build_public_value_ownership_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        result_cell_authority_receipt=result_cells,
        expected_result_cell_authority_sha256=result_cells.authority_sha256,
        stats_lossless_authorities=tuple(reversed(stats)),
        expected_stats_lossless_authority_sha256s=tuple(
            item.receipt.authority_sha256 for item in stats
        ),
        live_lossless_authority=live,
        expected_live_lossless_authority_receipt_sha256=live.receipt.receipt_sha256,
    )
    assert permuted == authority
    with pytest.raises(PublicValueAuthorityAdapterError, match="external pins"):
        build_public_value_ownership_authority(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            result_cell_authority_receipt=result_cells,
            expected_result_cell_authority_sha256=result_cells.authority_sha256,
            stats_lossless_authorities=stats,
            expected_stats_lossless_authority_sha256s=tuple(
                item.receipt.authority_sha256 for item in reversed(stats)
            ),
            live_lossless_authority=live,
            expected_live_lossless_authority_receipt_sha256=live.receipt.receipt_sha256,
        )


def test_mixed_families_use_one_bundle_order_and_exclusive_representations() -> None:
    wide_bundle, wide_cells = _combined_case()
    stats_bundle, stats_observation, _occurrences, _landings = _video_bundle(
        "VideoEvents",
        {"resultSets": [{"name": "Drift", "headers": [], "rowSet": []}]},
    )
    live_bundle = _live_bundle()
    bundle = _union_bundles(live_bundle, stats_bundle, wide_bundle)
    cells = _canonical_cells(bundle, list(wide_cells))
    stats = _stats_authority(
        bundle,
        stats_observation,
        include_response_residual=True,
    )
    live = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    authority = _build(bundle, cells, stats=(stats,), live=live)

    assert tuple(item.unit_ordinal for item in authority.expected_unit_inventory.units) == tuple(
        range(authority.expected_unit_inventory.unit_count)
    )
    assert tuple(item.observation_ordinal for item in authority.observations) == tuple(
        range(len(authority.observations))
    )
    assert {item.representation_kind for item in authority.representation_assignments} == {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
        "response_lossless_records_v1",
    }
    assert {item.source_input_kind for item in authority.representation_assignments} == {
        "parser_input_body",
        "declared_bodyless_packet",
    }
    assert {item.source_record_sha256 for item in authority.bindings}.issuperset(
        {item.record_sha256 for item in stats.records}
    )
    assert {item.source_record_sha256 for item in authority.bindings}.issuperset(
        {item.source_item_sha256 for item in live.records}
    )


def test_wide_plus_lossless_is_exclusively_stats_lossless_owned() -> None:
    bundle, rectangular_candidates = _wide_plus_lossless_case()
    observation = bundle.observations[0]
    stats = _stats_authority(bundle, observation)
    authority = _build(bundle, (), stats=(stats,))

    assert {item.representation_kind for item in authority.representation_assignments} == {
        "stats_lossless_records_v1"
    }
    assert {item.source_record_sha256 for item in authority.bindings} == {
        item.record_sha256 for item in stats.records
    }
    assert not (
        {item.cell_sha256 for item in rectangular_candidates}
        & {item.source_record_sha256 for item in authority.bindings}
    )


def test_fixed_zero_and_positive_residual_partitions_are_exact_complements() -> None:
    zero_bundle, _zero_observation, _zero_occurrences, _zero_landings = _video_bundle(
        "VideoDetails",
        {},
    )
    zero = _build(zero_bundle, ())
    assert zero.expected_unit_inventory.unit_count == 1
    assert zero.expected_unit_inventory.units[0].unit_kind == "response_fixed_zero"
    assert zero.receipt.response_fixed_zero_partition_count == 1
    assert zero.receipt.positive_response_residual_partition_count == 0
    assert zero.bindings == ()

    residual_bundle, residual_observation, _occurrences, landings = _video_bundle(
        "VideoDetails",
        {"future": 7},
    )
    assert any(item.landing_semantic == "response_fixed_zero" for item in landings)
    stats = _stats_authority(
        residual_bundle,
        residual_observation,
        include_response_residual=True,
    )
    residual = _build(residual_bundle, (), stats=(stats,))
    assert residual.expected_unit_inventory.unit_count == 1
    assert residual.expected_unit_inventory.units[0].unit_kind == "response_residual"
    assert residual.receipt.response_fixed_zero_partition_count == 0
    assert residual.receipt.positive_response_residual_partition_count == 1
    assert {item.source_record_sha256 for item in residual.bindings} == {
        item.record_sha256 for item in stats.records
    }


def test_hybrid_occurrence_and_residual_preserves_both_partitions() -> None:
    bundle, observation, _occurrences, _landings = _video_bundle(
        "VideoEvents",
        {"resultSets": [{"name": "Hybrid", "headers": [], "rowSet": []}]},
    )
    stats = _stats_authority(bundle, observation, include_response_residual=True)
    authority = _build(bundle, (), stats=(stats,))

    assert tuple(item.unit_kind for item in authority.expected_unit_inventory.units) == (
        "result_occurrence",
        "response_residual",
    )
    assert tuple(item.partition_kind for item in authority.partitions) == (
        "result_occurrence",
        "response_residual",
    )
    assert {item.source_record_sha256 for item in authority.bindings} == {
        item.record_sha256 for item in stats.records
    }


def test_cross_bundle_stats_authority_is_rejected_even_with_matching_side_pin() -> None:
    source_bundle, source_observation, _occurrences, _landings = _video_bundle(
        "VideoEvents",
        {"resultSets": [{"name": "Owned", "headers": [], "rowSet": []}]},
    )
    source_stats = _stats_authority(
        source_bundle,
        source_observation,
        include_response_residual=True,
    )
    other_bundle, _other_observation, _other_occurrences, _other_landings = _video_bundle(
        "VideoDetails",
        {},
    )
    bundle = _union_bundles(source_bundle, other_bundle)
    result_cells = validate_raw_result_cell_authority(bundle, ())
    live = _empty_live_authority(bundle)
    with pytest.raises(PublicValueAuthorityAdapterError, match="stats-lossless"):
        build_public_value_ownership_authority(
            bundle,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            result_cell_authority_receipt=result_cells,
            expected_result_cell_authority_sha256=result_cells.authority_sha256,
            stats_lossless_authorities=(source_stats,),
            expected_stats_lossless_authority_sha256s=(source_stats.receipt.authority_sha256,),
            live_lossless_authority=live,
            expected_live_lossless_authority_receipt_sha256=live.receipt.receipt_sha256,
        )


def test_post_construction_corrupted_stats_and_live_children_are_normalized() -> None:
    bundle, cells = _combined_case()
    live = _empty_live_authority(bundle)
    object.__setattr__(live, "records", (object(),))
    with pytest.raises(PublicValueAuthorityAdapterError, match="foreign exact child type"):
        _build(bundle, cells, live=live)

    stats_bundle, _rectangular_candidates = _wide_plus_lossless_case()
    stats = _stats_authority(stats_bundle, stats_bundle.observations[0])
    object.__setattr__(stats, "records", (object(),))
    with pytest.raises(PublicValueAuthorityAdapterError, match="foreign exact child type"):
        _build(stats_bundle, (), stats=(stats,))


def _synthetic_live_observation_sha256(ordinal: int) -> str:
    return f"{ordinal:064x}"


def _validate_synthetic_live_record_order(record_order: tuple[str, ...]) -> None:
    observation_sha256s = tuple(_synthetic_live_observation_sha256(item) for item in range(3))
    observation_record_sha256s = {
        observation_sha256: f"{ordinal + 10:064x}"
        for ordinal, observation_sha256 in enumerate(observation_sha256s)
    }
    observations = cast(
        "tuple[RequestObservationV2, ...]",
        tuple(
            SimpleNamespace(
                attempt=SimpleNamespace(
                    source_family="live",
                    observation_sha256=observation_sha256,
                ),
                observation_record_sha256=observation_record_sha256s[observation_sha256],
            )
            for observation_sha256 in observation_sha256s
        ),
    )
    authority = cast(
        "LiveLosslessValueAuthorityV1",
        SimpleNamespace(
            receipt=SimpleNamespace(
                raw_authority_bundle_sha256="f" * 64,
                selected_observation_count=len(observations),
            ),
            records=tuple(
                SimpleNamespace(
                    observation_sha256=observation_sha256,
                    observation_record_sha256=observation_record_sha256s.get(
                        observation_sha256,
                        "e" * 64,
                    ),
                )
                for observation_sha256 in record_order
            ),
            expected_units=SimpleNamespace(units=()),
        ),
    )
    adapter_module._validate_live_authority_join(
        authority=authority,
        bundle_sha256="f" * 64,
        observations=observations,
        occurrences_by_observation={item: () for item in observation_sha256s},
    )


def test_live_join_allows_zero_record_observation_gaps_in_one_pass() -> None:
    first = _synthetic_live_observation_sha256(0)
    third = _synthetic_live_observation_sha256(2)

    _validate_synthetic_live_record_order((first, first, third))


@pytest.mark.parametrize(
    ("record_order", "message"),
    (
        (
            (
                _synthetic_live_observation_sha256(0),
                _synthetic_live_observation_sha256(1),
                _synthetic_live_observation_sha256(0),
            ),
            "reopen",
        ),
        (
            (
                _synthetic_live_observation_sha256(2),
                _synthetic_live_observation_sha256(0),
            ),
            "observation order",
        ),
        (("a" * 64,), "observation order"),
    ),
)
def test_live_join_rejects_reopened_decreasing_and_foreign_positions(
    record_order: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(PublicValueAuthorityAdapterError, match=message):
        _validate_synthetic_live_record_order(record_order)


def test_parser_input_index_is_single_pass_and_supports_shared_physical_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"resultSets": [{"name": "Shared", "headers": [], "rowSet": []}]}
    details_bundle, _details_observation, _details_occurrences, _details_landings = _video_bundle(
        "VideoDetails", payload
    )
    events_bundle, _events_observation, _events_occurrences, _events_landings = _video_bundle(
        "VideoEvents", payload
    )
    bundle = _union_bundles(details_bundle, events_bundle)
    observations = adapter_module._ordered_selected_observations(bundle)
    assert len(bundle.objects) == 1
    assert len({item.body_object_sha256 for item in observations}) == 1

    with pytest.raises(PublicValueAuthorityAdapterError, match="duplicates one physical identity"):
        adapter_module._index_parser_inputs_by_object_sha((*bundle.objects, bundle.objects[0]))

    stats = tuple(
        _stats_authority(bundle, observation, include_response_residual=True)
        for observation in observations
    )
    original_index = adapter_module._index_parser_inputs_by_object_sha
    index_calls = 0

    def counted_index(objects):  # type: ignore[no-untyped-def]
        nonlocal index_calls
        index_calls += 1
        return original_index(objects)

    monkeypatch.setattr(
        adapter_module,
        "_index_parser_inputs_by_object_sha",
        counted_index,
    )
    authority = _build(bundle, (), stats=stats)
    assert index_calls == 1
    assert tuple(item.observation_sha256 for item in authority.observations) == tuple(
        item.attempt.observation_sha256 for item in observations
    )

    monkeypatch.setattr(
        adapter_module,
        "_index_parser_inputs_by_object_sha",
        lambda _objects: {},
    )
    with pytest.raises(PublicValueAuthorityAdapterError, match="lacks one exact parser input"):
        _build(bundle, (), stats=stats)


def test_aggregate_indexes_are_single_pass_and_builder_has_no_nested_full_rescans() -> None:
    class CountingTuple(tuple[object, ...]):
        scans = 0
        visits = 0

        def __iter__(self):  # type: ignore[no-untyped-def]
            type(self).scans += 1
            for item in super().__iter__():
                type(self).visits += 1
                yield item

    bundle, cells = _combined_case()
    observations = adapter_module._ordered_selected_observations(bundle)

    for function, values, expected_count in (
        (
            lambda counted: adapter_module._index_occurrences_by_observation(
                observations,
                counted,
            ),
            bundle.occurrences,
            len(bundle.occurrences),
        ),
        (
            lambda counted: adapter_module._index_landings_by_observation(
                observations,
                counted,
            ),
            bundle.landings,
            len(bundle.landings),
        ),
        (
            adapter_module._result_cell_source_index,
            cells,
            len(cells),
        ),
        (
            adapter_module._index_parser_inputs_by_object_sha,
            bundle.objects,
            len(bundle.objects),
        ),
    ):
        CountingTuple.scans = 0
        CountingTuple.visits = 0
        function(CountingTuple(values))  # type: ignore[arg-type]
        assert CountingTuple.scans == 1
        assert CountingTuple.visits == expected_count

    source = Path(adapter_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    build = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_authority"
    )
    public = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "build_public_value_ownership_authority"
    )

    def call_count(function: ast.FunctionDef, name: str) -> int:
        return sum(
            1
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
        )

    assert call_count(build, "_result_cell_source_index") == 1
    assert call_count(build, "_live_source_record_index") == 1
    assert call_count(public, "_index_occurrences_by_observation") == 1
    assert call_count(public, "_index_landings_by_observation") == 1
    assert call_count(public, "_index_parser_inputs_by_object_sha") == 1
    live_join = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_validate_live_authority_join"
    )
    selected_observation_order = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_ordered_selected_observations"
    )
    assert call_count(live_join, "sorted") == 0
    assert call_count(selected_observation_order, "sorted") == 1
    for index_name in (
        "_index_occurrences_by_observation",
        "_index_landings_by_observation",
        "_index_parser_inputs_by_object_sha",
    ):
        index_function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == index_name
        )
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sorted"
            for node in ast.walk(index_function)
        )
    stats_loop = next(
        node
        for node in ast.walk(public)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Call)
        and isinstance(node.iter.func, ast.Attribute)
        and isinstance(node.iter.func.value, ast.Name)
        and node.iter.func.value.id == "stats_by_observation"
        and node.iter.func.attr == "items"
    )

    def is_bundle_objects(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "bundle"
            and node.attr == "objects"
        )

    assert not any(
        isinstance(node, (ast.For, ast.comprehension)) and is_bundle_objects(node.iter)
        for node in ast.walk(stats_loop)
    )
    assert not {
        node.iter.id
        for node in ast.walk(build)
        if isinstance(node, ast.comprehension)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "observation_bindings"
    }
    assert "_result_cell_sources" not in source
    assert "_live_source_records" not in source
