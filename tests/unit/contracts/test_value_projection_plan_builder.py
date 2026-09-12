"""Production adapter tests for the frozen value-projection plan authority."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
from copy import copy
from dataclasses import fields
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from nbadb.contracts.body_blob_inventory import build_body_blob_inventory
from nbadb.contracts.declared_bodyless_packet import build_declared_bodyless_packet
from nbadb.contracts.declared_bodyless_packet_types import (
    DeclaredBodylessPacketReadbackReceiptV1,
)
from nbadb.contracts.live_lossless_value_authority import (
    LiveLosslessValueAuthorityV1,
    build_live_lossless_value_authority,
)
from nbadb.contracts.raw_request_authority import (
    RequestObservationV2,
    ResultOccurrenceV2,
)
from nbadb.contracts.raw_result_cell_authority import (
    RawResultCellAuthorityReceiptV2,
    validate_raw_result_cell_authority,
)
from nbadb.contracts.value_projection_plan import (
    ValueProjectionPlanError,
    ValueProjectionPlanOccurrenceV1,
    ValueProjectionPlanV1,
    validate_value_projection_plan,
)
from nbadb.contracts.value_projection_plan_builder import (
    ValueProjectionPlanBuilderError,
    build_value_projection_plan,
)
from nbadb.core.nba_api_runtime_contract import pinned_static_dataset_contract
from tests.unit.contracts import test_raw_request_authority as raw_request_fixtures
from tests.unit.contracts.test_body_blob_inventory import _readback_receipt
from tests.unit.contracts.test_public_value_authority_adapter import (
    _build,
    _empty_live_authority,
    _live_bundle,
    _stats_authority,
    _union_bundles,
)
from tests.unit.contracts.test_raw_request_authority import _video_bundle
from tests.unit.contracts.test_raw_result_cell_authority import (
    _canonical_cells,
    _combined_case,
    _stats_case,
)

if TYPE_CHECKING:
    from nbadb.contracts.declared_bodyless_packet_types import DeclaredBodylessPacketV1
    from nbadb.contracts.raw_request_authority import (
        RawRequestAuthorityBundleV2,
    )
    from nbadb.contracts.raw_result_cell_authority import RawNbaApiResultCellV2
    from nbadb.contracts.stats_lossless_value_authority import (
        StatsLosslessValueAuthorityV1,
    )


def _packet_source(
    observation: RequestObservationV2,
) -> tuple[DeclaredBodylessPacketV1, DeclaredBodylessPacketReadbackReceiptV1]:
    contract = pinned_static_dataset_contract(observation.attempt.endpoint_id)
    rows = getattr(importlib.import_module("nba_api.stats.library.data"), contract.source_symbol)
    packet_bytes = json.dumps(
        rows,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    packet = build_declared_bodyless_packet(
        observation=observation,
        expected_observation_sha256=observation.attempt.observation_sha256,
        expected_observation_record_sha256=observation.observation_record_sha256,
        packet_bytes=packet_bytes,
    )
    readback = DeclaredBodylessPacketReadbackReceiptV1.build(
        packet=packet,
        readback_bytes=packet_bytes,
        store_namespace_sha256="7" * 64,
        expected_packet_authority_sha256=packet.packet_authority_sha256,
    )
    return packet, readback


def _make_fixture(
    *,
    bundle: RawRequestAuthorityBundleV2,
    cells: tuple[RawNbaApiResultCellV2, ...],
    stats: tuple[StatsLosslessValueAuthorityV1, ...] = (),
    live: LiveLosslessValueAuthorityV1 | None = None,
    packets: tuple[DeclaredBodylessPacketV1, ...] = (),
    bodyless_readbacks: tuple[DeclaredBodylessPacketReadbackReceiptV1, ...] = (),
) -> dict[str, object]:
    result_receipt = validate_raw_result_cell_authority(bundle, cells)
    exact_live = _empty_live_authority(bundle) if live is None else live
    ownership = _build(bundle, cells, stats=stats, live=exact_live)
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    body_readback = _readback_receipt(bundle, inventory)
    return {
        "raw_bundle": bundle,
        "expected_raw_authority_bundle_sha256": bundle.bundle_sha256,
        "ownership_authority": ownership,
        "expected_ownership_receipt_sha256": ownership.receipt.receipt_sha256,
        "result_cell_authority_receipt": result_receipt,
        "expected_result_cell_authority_sha256": result_receipt.authority_sha256,
        "stats_lossless_authorities": stats,
        "expected_stats_lossless_authority_sha256s": tuple(
            item.receipt.authority_sha256 for item in stats
        ),
        "live_lossless_authority": exact_live,
        "expected_live_lossless_authority_receipt_sha256": (exact_live.receipt.receipt_sha256),
        "body_blob_inventory_readback_receipt": body_readback,
        "expected_body_blob_inventory_readback_receipt_sha256": body_readback.receipt_sha256,
        "declared_bodyless_packets": packets,
        "expected_declared_bodyless_packet_authority_sha256s": tuple(
            item.packet_authority_sha256 for item in packets
        ),
        "declared_bodyless_readback_receipts": bodyless_readbacks,
        "expected_declared_bodyless_readback_receipt_sha256s": tuple(
            item.receipt_sha256 for item in bodyless_readbacks
        ),
    }


@cache
def _default_fixture() -> dict[str, object]:
    bundle, cells = _stats_case()
    return _make_fixture(bundle=bundle, cells=cells)


def _fixture(
    *,
    bundle: RawRequestAuthorityBundleV2 | None = None,
    cells: tuple[RawNbaApiResultCellV2, ...] | None = None,
    stats: tuple[StatsLosslessValueAuthorityV1, ...] = (),
    live: LiveLosslessValueAuthorityV1 | None = None,
    packets: tuple[DeclaredBodylessPacketV1, ...] = (),
    bodyless_readbacks: tuple[DeclaredBodylessPacketReadbackReceiptV1, ...] = (),
) -> dict[str, object]:
    if (
        bundle is None
        and cells is None
        and not stats
        and live is None
        and not packets
        and not bodyless_readbacks
    ):
        return dict(_default_fixture())
    if bundle is None or cells is None:
        raise AssertionError("custom projection-plan fixture requires bundle and cells")
    return _make_fixture(
        bundle=bundle,
        cells=cells,
        stats=stats,
        live=live,
        packets=packets,
        bodyless_readbacks=bodyless_readbacks,
    )


def _zero_row_nonempty_header_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> RawRequestAuthorityBundleV2:
    original_payload = raw_request_fixtures._franchise_history_fallback_payload
    original_occurrence_build = ResultOccurrenceV2.build
    original_observation_build = RequestObservationV2.build

    def zero_row_payload(variant: str) -> dict[str, object]:
        payload = original_payload(variant)
        result_sets = payload["resultSets"]
        assert type(result_sets) is list
        for raw_result in result_sets:
            assert type(raw_result) is dict
            raw_result["rowSet"] = []
        return payload

    def zero_row_occurrence(**values: Any) -> ResultOccurrenceV2:
        if values.get("container_kind") == "nba_api_result_set" and values.get("row_count") == 0:
            values["presence"] = "present_empty"
        return original_occurrence_build(**values)

    def zero_row_observation(**values: Any) -> RequestObservationV2:
        values["outcome"] = "success_empty"
        return original_observation_build(**values)

    monkeypatch.setattr(
        raw_request_fixtures,
        "_franchise_history_fallback_payload",
        zero_row_payload,
    )
    monkeypatch.setattr(ResultOccurrenceV2, "build", zero_row_occurrence)
    monkeypatch.setattr(RequestObservationV2, "build", zero_row_observation)
    return raw_request_fixtures._strict_stats_bundle()


def test_parser_body_authorities_build_one_exact_projection_plan() -> None:
    plan = build_value_projection_plan(**_fixture())

    assert type(plan) is ValueProjectionPlanV1
    assert plan.observation_count == 1
    assert plan.observation_source_count == 1
    assert plan.observation_sources[0].source_input_kind == "parser_input_body"
    assert plan.occurrence_count == len(plan.expected_units) - 0
    assert plan.source_record_count == plan.binding_count
    assert (
        validate_value_projection_plan(
            plan,
            expected_plan_sha256=plan.plan_sha256,
            expected_raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
            expected_ownership_receipt_sha256=plan.ownership_receipt_sha256,
        )
        == plan
    )


def test_zero_row_nonempty_headers_preserve_exact_raw_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _zero_row_nonempty_header_bundle(monkeypatch)
    plan = build_value_projection_plan(**_fixture(bundle=bundle, cells=()))
    raw_occurrences = {item.occurrence_sha256: item for item in bundle.occurrences}

    assert plan.occurrence_count == len(bundle.occurrences)
    for occurrence_plan in plan.occurrence_plans:
        raw_occurrence = raw_occurrences[occurrence_plan.occurrence_sha256]
        assert occurrence_plan.result_presence == "present_empty"
        assert occurrence_plan.row_count == 0
        assert occurrence_plan.header_count > 0
        assert occurrence_plan.ordered_headers_json == raw_occurrence.ordered_headers_json
        assert occurrence_plan.ordered_headers_sha256 == (raw_occurrence.ordered_headers_sha256)
        assert occurrence_plan.ordered_headers() == raw_occurrence.ordered_headers()
    assert any(
        occurrence_plan.ordered_headers() != tuple(sorted(occurrence_plan.ordered_headers()))
        for occurrence_plan in plan.occurrence_plans
    )


def test_coordinated_header_order_reseal_changes_the_external_plan_pin() -> None:
    plan = build_value_projection_plan(**_fixture())
    original = plan.occurrence_plans[0]
    reversed_headers = tuple(reversed(original.ordered_headers()))
    assert reversed_headers != original.ordered_headers()
    forged_json = json.dumps(
        list(reversed_headers),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    forged_occurrence = ValueProjectionPlanOccurrenceV1.build(
        **{
            **{
                item.name: getattr(original, item.name)
                for item in fields(ValueProjectionPlanOccurrenceV1)
                if item.name != "occurrence_plan_sha256"
            },
            "ordered_headers_json": forged_json,
            "ordered_headers_sha256": hashlib.sha256(forged_json.encode("utf-8")).hexdigest(),
        }
    )
    occurrence_plans = list(plan.occurrence_plans)
    occurrence_plans[original.occurrence_plan_ordinal] = forged_occurrence
    forged_plan = ValueProjectionPlanV1.build(
        raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
        ownership_receipt_sha256=plan.ownership_receipt_sha256,
        expected_unit_inventory_sha256=plan.expected_unit_inventory_sha256,
        expected_units=plan.expected_units,
        assignments=plan.assignments,
        ownership_observations=plan.ownership_observations,
        ownership_partitions=plan.ownership_partitions,
        ownership_bindings=plan.ownership_bindings,
        observation_sources=plan.observation_sources,
        occurrence_plans=tuple(occurrence_plans),
        source_record_plans=plan.source_record_plans,
    )

    assert forged_plan.plan_sha256 != plan.plan_sha256
    with pytest.raises(ValueProjectionPlanError, match="external authority pins"):
        validate_value_projection_plan(
            forged_plan,
            expected_plan_sha256=plan.plan_sha256,
            expected_raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
            expected_ownership_receipt_sha256=plan.ownership_receipt_sha256,
        )


def test_bodyless_static_source_is_explicit_and_value_free() -> None:
    bundle, cells = _combined_case()
    static_observations = tuple(
        item for item in bundle.observations if item.attempt.source_family == "static"
    )
    assert len(static_observations) == 1
    packet, readback = _packet_source(static_observations[0])
    values = _fixture(
        bundle=bundle,
        cells=cells,
        packets=(packet,),
        bodyless_readbacks=(readback,),
    )
    plan = build_value_projection_plan(**values)

    sources = {item.source_input_kind: item for item in plan.observation_sources}
    assert sources["declared_bodyless_packet"].source_family == "static"
    assert sources["declared_bodyless_packet"].bodyless_packet_sha256 == (
        packet.packet_authority_sha256
    )
    assert sources["declared_bodyless_packet"].body_blob_sha256 is None
    encoded = plan.canonical_bytes()
    assert packet.to_canonical_bytes() not in encoded
    assert b"canonical_json" not in encoded


def test_mixed_stats_static_live_authorities_preserve_bundle_global_order() -> None:
    wide_bundle, wide_cells = _combined_case()
    stats_bundle, stats_observation, _occurrences, _landings = _video_bundle(
        "VideoEvents",
        {"resultSets": [{"name": "Drift", "headers": [], "rowSet": []}]},
    )
    live_bundle = _live_bundle()
    bundle = _union_bundles(live_bundle, stats_bundle, wide_bundle)
    cells = _canonical_cells(bundle, list(wide_cells))
    stats = _stats_authority(bundle, stats_observation, include_response_residual=True)
    live = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    static_observation = next(
        item for item in bundle.observations if item.attempt.source_family == "static"
    )
    packet, readback = _packet_source(static_observation)
    plan = build_value_projection_plan(
        **_fixture(
            bundle=bundle,
            cells=cells,
            stats=(stats,),
            live=live,
            packets=(packet,),
            bodyless_readbacks=(readback,),
        )
    )

    assert tuple(item.observation_ordinal for item in plan.observation_sources) == tuple(
        range(plan.observation_count)
    )
    assert tuple(item.occurrence_plan_ordinal for item in plan.occurrence_plans) == tuple(
        range(plan.occurrence_count)
    )
    assert tuple(item.source_record_plan_ordinal for item in plan.source_record_plans) == tuple(
        range(plan.source_record_count)
    )
    assert {item.representation_kind for item in plan.assignments} == {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
        "response_lossless_records_v1",
    }
    no_header_occurrence = next(
        item for item in plan.occurrence_plans if item.result_name == "Drift"
    )
    assert no_header_occurrence.header_count == 0
    assert no_header_occurrence.ordered_headers_json == "[]"
    assert no_header_occurrence.ordered_headers() == ()


def test_fixed_zero_and_positive_residual_are_explicit_complements() -> None:
    zero_bundle, _observation, _occurrences, _landings = _video_bundle(
        "VideoDetails",
        {},
    )
    zero = build_value_projection_plan(
        **_fixture(
            bundle=zero_bundle,
            cells=(),
        )
    )
    assert tuple(item.unit_kind for item in zero.expected_units) == ("response_fixed_zero",)
    assert zero.occurrence_plans == ()
    assert zero.source_record_plans == ()

    residual_bundle, observation, _occurrences, _landings = _video_bundle(
        "VideoDetails",
        {"future": 7},
    )
    stats = _stats_authority(
        residual_bundle,
        observation,
        include_response_residual=True,
    )
    residual = build_value_projection_plan(
        **_fixture(
            bundle=residual_bundle,
            cells=(),
            stats=(stats,),
        )
    )
    assert tuple(item.unit_kind for item in residual.expected_units) == ("response_residual",)
    assert residual.occurrence_plans == ()
    assert residual.source_record_count == len(stats.records)
    assert {item.unit_kind for item in residual.source_record_plans} == {"response_residual"}


def test_missing_body_source_and_cross_observation_packet_fail_closed() -> None:
    values = _fixture()
    values["body_blob_inventory_readback_receipt"] = _fixture(
        bundle=_union_bundles(),
        cells=(),
    )["body_blob_inventory_readback_receipt"]
    with pytest.raises(ValueProjectionPlanBuilderError):
        build_value_projection_plan(**values)

    bundle, cells = _combined_case()
    static_observation = next(
        item for item in bundle.observations if item.attempt.source_family == "static"
    )
    packet, readback = _packet_source(static_observation)
    forged = copy(readback)
    object.__setattr__(forged, "observation_sha256", "0" * 64)
    values = _fixture(
        bundle=bundle,
        cells=cells,
        packets=(packet,),
        bodyless_readbacks=(forged,),
    )
    with pytest.raises(ValueProjectionPlanBuilderError):
        build_value_projection_plan(**values)


def test_external_pin_is_rejected_before_foreign_children() -> None:
    values = _fixture()
    values["expected_raw_authority_bundle_sha256"] = "not-a-pin"
    values["ownership_authority"] = object()
    with pytest.raises(ValueProjectionPlanBuilderError, match="expected Raw bundle"):
        build_value_projection_plan(**values)


def test_authority_denominator_is_rejected_before_foreign_item_traversal() -> None:
    values = _fixture()
    values["stats_lossless_authorities"] = (object(),)
    with pytest.raises(
        ValueProjectionPlanBuilderError,
        match="authority and external-pin denominators differ",
    ):
        build_value_projection_plan(**values)


@pytest.mark.parametrize(
    "pin_name",
    (
        "expected_ownership_receipt_sha256",
        "expected_result_cell_authority_sha256",
        "expected_live_lossless_authority_receipt_sha256",
        "expected_body_blob_inventory_readback_receipt_sha256",
    ),
)
def test_every_external_authority_pin_is_fail_closed(pin_name: str) -> None:
    values = _fixture()
    values[pin_name] = "0" * 64
    with pytest.raises(ValueProjectionPlanBuilderError, match="external pin"):
        build_value_projection_plan(**values)


def test_bool_and_exact_dto_subclasses_are_rejected() -> None:
    values = _fixture()
    values["expected_raw_authority_bundle_sha256"] = True
    with pytest.raises(ValueProjectionPlanBuilderError, match="expected Raw bundle"):
        build_value_projection_plan(**values)

    class ResultReceiptSubclass(RawResultCellAuthorityReceiptV2):
        pass

    values = _fixture()
    exact = values["result_cell_authority_receipt"]
    assert type(exact) is RawResultCellAuthorityReceiptV2
    values["result_cell_authority_receipt"] = ResultReceiptSubclass(
        **{item.name: getattr(exact, item.name) for item in fields(RawResultCellAuthorityReceiptV2)}
    )
    with pytest.raises(ValueProjectionPlanBuilderError, match="foreign exact type"):
        build_value_projection_plan(**values)


def test_raw_header_preimage_scalars_require_exact_builtin_types() -> None:
    class ForeignText(str):
        pass

    original_values = _fixture()
    original_bundle = original_values["raw_bundle"]
    assert hasattr(original_bundle, "occurrences")
    original_occurrence = original_bundle.occurrences[0]
    for field_name, hostile in (
        (
            "ordered_headers_json",
            ForeignText(original_occurrence.ordered_headers_json),
        ),
        (
            "ordered_headers_sha256",
            ForeignText(original_occurrence.ordered_headers_sha256),
        ),
        ("header_count", True),
    ):
        values = _fixture()
        bundle = copy(values["raw_bundle"])
        occurrence = copy(bundle.occurrences[0])
        object.__setattr__(occurrence, field_name, hostile)
        object.__setattr__(bundle, "occurrences", (occurrence, *bundle.occurrences[1:]))
        values["raw_bundle"] = bundle
        with pytest.raises(ValueProjectionPlanBuilderError, match="foreign exact child type"):
            build_value_projection_plan(**values)


def test_hostile_exact_live_child_is_normalized_without_private_detail() -> None:
    values = _fixture()
    live = values["live_lossless_authority"]
    assert type(live) is LiveLosslessValueAuthorityV1
    hostile = copy(live)
    object.__setattr__(hostile, "records", (object(),))
    values["live_lossless_authority"] = hostile
    with pytest.raises(ValueProjectionPlanBuilderError, match="foreign exact child") as caught:
        build_value_projection_plan(**values)
    assert caught.value.__cause__ is None


def test_duplicate_stats_authority_is_rejected_as_dual_source_ownership() -> None:
    bundle, observation, _occurrences, _landings = _video_bundle(
        "VideoDetails",
        {"future": 7},
    )
    stats = _stats_authority(bundle, observation, include_response_residual=True)
    values = _fixture(bundle=bundle, cells=(), stats=(stats,))
    values["stats_lossless_authorities"] = (stats, stats)
    values["expected_stats_lossless_authority_sha256s"] = (
        stats.receipt.authority_sha256,
        stats.receipt.authority_sha256,
    )

    with pytest.raises(ValueProjectionPlanBuilderError):
        build_value_projection_plan(**values)


@pytest.mark.parametrize("authority_name", ("ownership_authority", "live_lossless_authority"))
def test_foreign_receipt_child_is_rejected_before_pin_member_access(
    authority_name: str,
) -> None:
    values = _fixture()
    authority = copy(values[authority_name])
    object.__setattr__(authority, "receipt", object())
    values[authority_name] = authority

    with pytest.raises(
        ValueProjectionPlanBuilderError,
        match="external-pin receipt has a foreign exact type",
    ) as caught:
        build_value_projection_plan(**values)
    assert caught.value.__cause__ is None


def test_missing_receipt_slot_is_normalized_without_attribute_leakage() -> None:
    values = _fixture()
    authority = copy(values["live_lossless_authority"])
    object.__delattr__(authority, "receipt")
    values["live_lossless_authority"] = authority

    with pytest.raises(
        ValueProjectionPlanBuilderError,
        match="authorities failed exact canonical replay",
    ) as caught:
        build_value_projection_plan(**values)
    assert caught.value.__cause__ is None


def test_builder_has_closed_import_boundary_and_no_full_rescan_calls() -> None:
    path = Path("src/nbadb/contracts/value_projection_plan_builder.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = ("nbadb.extract", "nbadb.orchestrate", "nbadb.schemas", "nbadb.kaggle")
    imported: list[str] = []
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            calls.append(node.func.attr)
    assert not any(name.startswith(forbidden) for name in imported)
    assert not ({"count", "index"} & set(calls))

    occurrence_builder = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_occurrence_plans"
    )
    occurrence_calls = {
        node.func.id
        for node in ast.walk(occurrence_builder)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    occurrence_attribute_calls = {
        node.func.attr
        for node in ast.walk(occurrence_builder)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "sorted" not in occurrence_calls
    assert not ({"count", "index", "sort", "ordered_headers"} & occurrence_attribute_calls)
    assert (
        sum(
            1
            for node in ast.walk(occurrence_builder)
            if isinstance(node, ast.Attribute) and node.attr == "ordered_headers_json"
        )
        == 1
    )
