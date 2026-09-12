"""Focused closure tests for the pure W2 operation cross-child builder."""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
from copy import copy
from functools import cache
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest

from nbadb.contracts.body_blob_inventory import build_body_blob_inventory
from nbadb.contracts.independent_body_value_projection_builder import (
    INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256,
    build_independent_body_value_projection,
)
from nbadb.contracts.independent_result_cell_builder import (
    build_independent_result_cell_authority,
)
from nbadb.contracts.independent_stats_lossless_authority_builder import (
    build_independent_stats_lossless_authorities,
)
from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
    build_live_lossless_value_authority,
)
from nbadb.contracts.lossless_ownership import LosslessOwnershipAuthorityV1
from nbadb.contracts.public_table_value_projection import (
    RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
    RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
    RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
)
from nbadb.contracts.route_field_landing_builder import (
    RawNbaApiRouteFieldLandingAuthorityReceiptV1,
    RawNbaApiRouteFieldLandingAuthorityV1,
    build_raw_nba_api_route_field_landing_authority,
)
from nbadb.contracts.stats_lossless_value_authority import (
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
)
from nbadb.contracts.value_projection import BodyValueProjectionReceiptV1
from nbadb.contracts.value_projection_equality import (
    ValueProjectionEqualityReceiptV1,
)
from nbadb.contracts.value_projection_plan_builder import build_value_projection_plan
from nbadb.contracts.w2_operation import W2OperationReceiptV1
from nbadb.contracts.w2_operation_builder import (
    W2OperationBuilderError,
    build_w2_operation,
)
from nbadb.core.nba_api_runtime_contract import pinned_static_dataset_contract
from nbadb.orchestrate.staging_batches import (
    CommittedStagingChunkReceiptV2,
    CommittedStagingFrameReadbackV2,
)
from nbadb.schemas.raw.nba_api_w2_operation import (
    RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
)
from tests.unit.contracts.test_public_table_value_projection import _project
from tests.unit.contracts.test_public_value_authority_adapter import _live_bundle
from tests.unit.contracts.test_raw_request_authority import (
    _static_bundle,
    _stats_fallback_bundle,
    _video_bundle,
)
from tests.unit.contracts.test_raw_result_cell_authority import _stats_case
from tests.unit.contracts.test_route_field_landing_builder import (
    _alias_receipts,
    _route_receipts,
)
from tests.unit.contracts.test_value_projection_equality import _fully_reseal_receipt_row
from tests.unit.contracts.test_value_projection_plan_builder import _fixture as _plan_fixture
from tests.unit.contracts.test_value_projection_plan_builder import _packet_source


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _committed_receipt(landing: Any) -> CommittedStagingChunkReceiptV2:
    return CommittedStagingChunkReceiptV2(
        chunk_id=landing.chunk_id,
        staging_key=landing.staging_key,
        canonical_frame_format=landing.canonical_frame_format,
        frame_content_hash_contract=landing.frame_content_hash_contract,
        frame_schema_hash_contract=landing.frame_schema_hash_contract,
        content_hash=landing.content_hash,
        persisted_row_count=landing.persisted_row_count,
        persisted_content_sha256=landing.persisted_content_sha256,
        persisted_schema_sha256=landing.persisted_schema_sha256,
        logical_call_receipt_sha256=landing.logical_call_receipt_sha256,
        provider_authority_sha256=landing.provider_authority_sha256,
        logical_parameters_sha256=landing.logical_parameters_sha256,
        result_route_id=landing.result_route_id,
    )


@cache
def _valid_values() -> dict[str, object]:
    bundle, _observation, _occurrences, landings = _video_bundle("VideoDetails", {})
    packets: tuple[object, ...] = ()
    bodyless_readbacks: tuple[object, ...] = ()
    packet_bytes: tuple[bytes, ...] = ()
    result_authority = build_independent_result_cell_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        declared_bodyless_packets=packets,
        expected_declared_bodyless_packet_authority_sha256s=(),
        declared_bodyless_packet_bytes=packet_bytes,
    )
    stats_authorities = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    live_authority = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    plan_values = _plan_fixture(
        bundle=bundle,
        cells=result_authority.public_table_proof.cells,
        stats=stats_authorities,
        live=live_authority,
        packets=cast("Any", packets),
        bodyless_readbacks=cast("Any", bodyless_readbacks),
    )
    plan = build_value_projection_plan(**cast("Any", plan_values))
    ownership = plan_values["ownership_authority"]
    route_receipts = _route_receipts(bundle, zero_fields=True)
    alias_receipts = _alias_receipts(bundle, route_receipts)
    route_authority = build_raw_nba_api_route_field_landing_authority(
        raw_authority_bundle=bundle,
        expected_unit_inventory=ownership.expected_unit_inventory,
        representation_assignments=ownership.representation_assignments,
        result_cell_authority_receipt=result_authority,
        lossless_ownership_authority=ownership,
        route_landing_receipts=route_receipts,
        canonical_alias_receipts=alias_receipts,
    )
    route_rows = tuple(item.to_row() for item in route_authority.rows)
    result_rows = tuple(item.to_row() for item in result_authority.public_table_proof.cells)
    stats_rows = tuple(row for authority in stats_authorities for row in authority.public_rows())
    live_rows = live_authority.public_rows()
    public = _project(
        plan,
        cells=result_rows,
        stats_rows=stats_rows,
        live_rows=live_rows,
        route_rows=route_rows,
    )
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    body = build_independent_body_value_projection(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        ownership_authority=ownership,
        expected_ownership_receipt_sha256=ownership.receipt.receipt_sha256,
        plan=plan,
        expected_plan_sha256=plan.plan_sha256,
        body_blob_inventory=inventory,
        expected_body_blob_inventory_sha256=inventory.inventory_sha256,
        body_blob_inventory_readback_receipt=plan_values["body_blob_inventory_readback_receipt"],
        expected_body_blob_inventory_readback_receipt_sha256=plan_values[
            "expected_body_blob_inventory_readback_receipt_sha256"
        ],
        declared_bodyless_packets=packets,
        expected_declared_bodyless_packet_authority_sha256s=(),
        declared_bodyless_readback_receipts=bodyless_readbacks,
        expected_declared_bodyless_readback_receipt_sha256s=(),
        declared_bodyless_packet_bytes=packet_bytes,
    )
    equality = ValueProjectionEqualityReceiptV1.build(
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_ownership_receipt_sha256=ownership.receipt.receipt_sha256,
        expected_plan_sha256=plan.plan_sha256,
        body_projection=body.projection,
        expected_body_projection_sha256=body.projection.projection_sha256,
        body_partitions=body.partitions,
        body_items=body.items,
        public_projection=public.projection,
        expected_public_projection_sha256=public.projection.projection_sha256,
        public_partitions=public.partitions,
        public_items=public.items,
    )
    readback = CommittedStagingFrameReadbackV2.build(
        committed_receipt=_committed_receipt(landings[0]),
        frame=pl.DataFrame(),
    )
    return {
        "raw_bundle": bundle,
        "expected_raw_authority_bundle_sha256": bundle.bundle_sha256,
        "raw_observations": bundle.observations,
        "committed_staging_readbacks": (readback,),
        "expected_committed_staging_readback_sha256s": (readback.readback_receipt_sha256,),
        "body_value_projection_receipt": body.receipt,
        "expected_body_value_projection_receipt_sha256": body.receipt.receipt_sha256,
        "body_projection": body.projection,
        "expected_body_projection_sha256": body.projection.projection_sha256,
        "body_partitions": body.partitions,
        "body_items": body.items,
        "ownership_receipt": ownership.receipt,
        "expected_ownership_receipt_sha256": ownership.receipt.receipt_sha256,
        "expected_unit_inventory": ownership.expected_unit_inventory,
        "representation_assignments": ownership.representation_assignments,
        "ownership_observations": ownership.observations,
        "ownership_partitions": ownership.partitions,
        "ownership_bindings": ownership.bindings,
        "result_cell_authority_receipt": result_authority,
        "expected_result_cell_authority_sha256": result_authority.authority_sha256,
        "stats_lossless_authorities": stats_authorities,
        "expected_stats_lossless_authority_sha256s": tuple(
            item.receipt.authority_sha256 for item in stats_authorities
        ),
        "live_lossless_authority": live_authority,
        "expected_live_lossless_authority_receipt_sha256": live_authority.receipt.receipt_sha256,
        "body_blob_inventory": inventory,
        "expected_body_blob_inventory_sha256": inventory.inventory_sha256,
        "body_blob_inventory_readback_receipt": plan_values["body_blob_inventory_readback_receipt"],
        "expected_body_blob_inventory_readback_receipt_sha256": plan_values[
            "expected_body_blob_inventory_readback_receipt_sha256"
        ],
        "declared_bodyless_packets": plan_values["declared_bodyless_packets"],
        "expected_declared_bodyless_packet_authority_sha256s": plan_values[
            "expected_declared_bodyless_packet_authority_sha256s"
        ],
        "declared_bodyless_readback_receipts": plan_values["declared_bodyless_readback_receipts"],
        "expected_declared_bodyless_readback_receipt_sha256s": plan_values[
            "expected_declared_bodyless_readback_receipt_sha256s"
        ],
        "declared_bodyless_packet_bytes": packet_bytes,
        "plan": plan,
        "expected_plan_sha256": plan.plan_sha256,
        "route_field_landing_receipt": route_authority.receipt,
        "expected_route_field_landing_receipt_sha256": route_authority.receipt.receipt_sha256,
        "route_landing_receipts": route_receipts,
        "expected_route_landing_receipt_sha256s": tuple(
            item.landing_receipt_sha256 for item in route_receipts
        ),
        "canonical_alias_receipts": alias_receipts,
        "expected_canonical_alias_receipt_sha256s": tuple(
            item.receipt_sha256 for item in alias_receipts
        ),
        "route_field_landing_authority_rows": route_authority.rows,
        "public_table_value_projection_receipt": public.receipt,
        "expected_public_table_value_projection_receipt_sha256": public.receipt.receipt_sha256,
        "public_projection": public.projection,
        "expected_public_projection_sha256": public.projection.projection_sha256,
        "public_partitions": public.partitions,
        "public_items": public.items,
        "value_projection_equality_receipt": equality,
        "expected_value_projection_equality_receipt_sha256": equality.receipt_sha256,
        "result_cell_schema_sha256": RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
        "result_cell_rows": result_rows,
        "stats_lossless_schema_sha256": STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
        "stats_lossless_rows": stats_rows,
        "live_lossless_schema_sha256": LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        "live_lossless_rows": live_rows,
        "value_representation_schema_sha256": RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
        "value_representation_rows": tuple(item.to_row() for item in plan.assignments),
        "route_field_landing_schema_sha256": RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
        "route_field_landing_rows": route_rows,
        "expected_w2_operation_schema_sha256": RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
    }


def _static_packet_bytes(endpoint_id: str) -> bytes:
    contract = pinned_static_dataset_contract(endpoint_id)
    rows = getattr(importlib.import_module("nba_api.stats.library.data"), contract.source_symbol)
    return json.dumps(
        rows,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _source_values(
    bundle: Any,
    *,
    packets: tuple[object, ...] = (),
    bodyless_readbacks: tuple[object, ...] = (),
    packet_bytes: tuple[bytes, ...] = (),
    zero_route_fields: bool = False,
) -> dict[str, object]:
    """Build every retained W2 witness from the same independent source bytes."""

    packet_pins = tuple(cast("Any", item).packet_authority_sha256 for item in packets)
    bodyless_readback_pins = tuple(cast("Any", item).receipt_sha256 for item in bodyless_readbacks)
    result_authority = build_independent_result_cell_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        declared_bodyless_packets=packets,
        expected_declared_bodyless_packet_authority_sha256s=packet_pins,
        declared_bodyless_packet_bytes=packet_bytes,
    )
    stats_authorities = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    live_authority = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    plan_values = _plan_fixture(
        bundle=bundle,
        cells=result_authority.public_table_proof.cells,
        stats=stats_authorities,
        live=live_authority,
        packets=cast("Any", packets),
        bodyless_readbacks=cast("Any", bodyless_readbacks),
    )
    plan = build_value_projection_plan(**cast("Any", plan_values))
    ownership = plan_values["ownership_authority"]
    route_receipts = _route_receipts(bundle, zero_fields=zero_route_fields)
    alias_receipts = _alias_receipts(bundle, route_receipts)
    route_authority = build_raw_nba_api_route_field_landing_authority(
        raw_authority_bundle=bundle,
        expected_unit_inventory=ownership.expected_unit_inventory,
        representation_assignments=ownership.representation_assignments,
        result_cell_authority_receipt=result_authority,
        lossless_ownership_authority=ownership,
        route_landing_receipts=route_receipts,
        canonical_alias_receipts=alias_receipts,
    )
    result_rows = tuple(item.to_row() for item in result_authority.public_table_proof.cells)
    stats_rows = tuple(row for authority in stats_authorities for row in authority.public_rows())
    live_rows = live_authority.public_rows()
    route_rows = tuple(item.to_row() for item in route_authority.rows)
    public = _project(
        plan,
        cells=result_rows,
        stats_rows=stats_rows,
        live_rows=live_rows,
        route_rows=route_rows,
    )
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    body = build_independent_body_value_projection(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        ownership_authority=ownership,
        expected_ownership_receipt_sha256=ownership.receipt.receipt_sha256,
        plan=plan,
        expected_plan_sha256=plan.plan_sha256,
        body_blob_inventory=inventory,
        expected_body_blob_inventory_sha256=inventory.inventory_sha256,
        body_blob_inventory_readback_receipt=plan_values["body_blob_inventory_readback_receipt"],
        expected_body_blob_inventory_readback_receipt_sha256=plan_values[
            "expected_body_blob_inventory_readback_receipt_sha256"
        ],
        declared_bodyless_packets=packets,
        expected_declared_bodyless_packet_authority_sha256s=packet_pins,
        declared_bodyless_readback_receipts=bodyless_readbacks,
        expected_declared_bodyless_readback_receipt_sha256s=bodyless_readback_pins,
        declared_bodyless_packet_bytes=packet_bytes,
    )
    equality = ValueProjectionEqualityReceiptV1.build(
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_ownership_receipt_sha256=ownership.receipt.receipt_sha256,
        expected_plan_sha256=plan.plan_sha256,
        body_projection=body.projection,
        expected_body_projection_sha256=body.projection.projection_sha256,
        body_partitions=body.partitions,
        body_items=body.items,
        public_projection=public.projection,
        expected_public_projection_sha256=public.projection.projection_sha256,
        public_partitions=public.partitions,
        public_items=public.items,
    )
    values = dict(_valid_values())
    values.update(
        {
            "raw_bundle": bundle,
            "expected_raw_authority_bundle_sha256": bundle.bundle_sha256,
            "raw_observations": bundle.observations,
            "body_value_projection_receipt": body.receipt,
            "expected_body_value_projection_receipt_sha256": body.receipt.receipt_sha256,
            "body_projection": body.projection,
            "expected_body_projection_sha256": body.projection.projection_sha256,
            "body_partitions": body.partitions,
            "body_items": body.items,
            "ownership_receipt": ownership.receipt,
            "expected_ownership_receipt_sha256": ownership.receipt.receipt_sha256,
            "expected_unit_inventory": ownership.expected_unit_inventory,
            "representation_assignments": ownership.representation_assignments,
            "ownership_observations": ownership.observations,
            "ownership_partitions": ownership.partitions,
            "ownership_bindings": ownership.bindings,
            "result_cell_authority_receipt": result_authority,
            "expected_result_cell_authority_sha256": result_authority.authority_sha256,
            "stats_lossless_authorities": stats_authorities,
            "expected_stats_lossless_authority_sha256s": tuple(
                item.receipt.authority_sha256 for item in stats_authorities
            ),
            "live_lossless_authority": live_authority,
            "expected_live_lossless_authority_receipt_sha256": (
                live_authority.receipt.receipt_sha256
            ),
            "body_blob_inventory": inventory,
            "expected_body_blob_inventory_sha256": inventory.inventory_sha256,
            "body_blob_inventory_readback_receipt": plan_values[
                "body_blob_inventory_readback_receipt"
            ],
            "expected_body_blob_inventory_readback_receipt_sha256": plan_values[
                "expected_body_blob_inventory_readback_receipt_sha256"
            ],
            "declared_bodyless_packets": packets,
            "expected_declared_bodyless_packet_authority_sha256s": packet_pins,
            "declared_bodyless_readback_receipts": bodyless_readbacks,
            "expected_declared_bodyless_readback_receipt_sha256s": bodyless_readback_pins,
            "declared_bodyless_packet_bytes": packet_bytes,
            "plan": plan,
            "expected_plan_sha256": plan.plan_sha256,
            "route_field_landing_receipt": route_authority.receipt,
            "expected_route_field_landing_receipt_sha256": (route_authority.receipt.receipt_sha256),
            "route_landing_receipts": route_receipts,
            "expected_route_landing_receipt_sha256s": tuple(
                item.landing_receipt_sha256 for item in route_receipts
            ),
            "canonical_alias_receipts": alias_receipts,
            "expected_canonical_alias_receipt_sha256s": tuple(
                item.receipt_sha256 for item in alias_receipts
            ),
            "route_field_landing_authority_rows": route_authority.rows,
            "public_table_value_projection_receipt": public.receipt,
            "expected_public_table_value_projection_receipt_sha256": (
                public.receipt.receipt_sha256
            ),
            "public_projection": public.projection,
            "expected_public_projection_sha256": public.projection.projection_sha256,
            "public_partitions": public.partitions,
            "public_items": public.items,
            "value_projection_equality_receipt": equality,
            "expected_value_projection_equality_receipt_sha256": equality.receipt_sha256,
            "result_cell_rows": result_rows,
            "stats_lossless_rows": stats_rows,
            "live_lossless_rows": live_rows,
            "value_representation_rows": tuple(item.to_row() for item in plan.assignments),
            "route_field_landing_rows": route_rows,
        }
    )
    return values


def _build(**changes: object) -> W2OperationReceiptV1:
    values = dict(_valid_values())
    values.update(changes)
    return build_w2_operation(**values)


def _build_with_unrelated_staging_bypassed(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, object],
) -> W2OperationReceiptV1:
    import nbadb.contracts.w2_operation_builder as module

    readbacks = cast(
        "tuple[CommittedStagingFrameReadbackV2, ...]", values["committed_staging_readbacks"]
    )
    monkeypatch.setattr(module, "_validate_readbacks", lambda **_kwargs: readbacks)
    return build_w2_operation(**values)


def _resealed_body_receipt(
    values: dict[str, object],
    *,
    policy_sha256: str,
    declared_bodyless_authority_sha256: str,
) -> BodyValueProjectionReceiptV1:
    plan = cast("Any", values["plan"])
    projection = cast("Any", values["body_projection"])
    parser_sources = tuple(
        item for item in plan.observation_sources if item.source_input_kind == "parser_input_body"
    )
    bodyless_sources = tuple(
        item
        for item in plan.observation_sources
        if item.source_input_kind == "declared_bodyless_packet"
    )
    return BodyValueProjectionReceiptV1.build(
        raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
        body_projection_policy_sha256=policy_sha256,
        body_blob_inventory_sha256=cast("Any", values["body_blob_inventory"]).inventory_sha256,
        declared_bodyless_authority_sha256=declared_bodyless_authority_sha256,
        expected_projection_sha256=projection.projection_sha256,
        projection=projection,
        body_blob_sha256s=tuple(cast("str", item.body_blob_sha256) for item in parser_sources),
        body_blob_readback_sha256s=tuple(
            cast("str", item.body_blob_readback_sha256) for item in parser_sources
        ),
        parser_input_object_sha256s=tuple(
            cast("str", item.parser_input_object_sha256) for item in parser_sources
        ),
        body_blob_byte_count=sum(item.payload_byte_count for item in parser_sources),
        bodyless_packet_sha256s=tuple(
            cast("str", item.bodyless_packet_sha256) for item in bodyless_sources
        ),
        bodyless_readback_sha256s=tuple(
            cast("str", item.bodyless_readback_sha256) for item in bodyless_sources
        ),
        bodyless_packet_byte_count=sum(item.payload_byte_count for item in bodyless_sources),
        observation_source_sha256s=tuple(item.source_sha256 for item in plan.observation_sources),
    )


def test_builds_exact_scalar_operation_from_all_actual_children() -> None:
    operation = _build()
    values = _valid_values()
    body = values["body_value_projection_receipt"]
    public = values["public_table_value_projection_receipt"]
    equality = values["value_projection_equality_receipt"]

    assert type(operation) is W2OperationReceiptV1
    assert operation.body_value_projection_receipt_sha256 == body.receipt_sha256
    assert operation.public_table_value_projection_receipt_sha256 == public.receipt_sha256
    assert operation.value_projection_equality_receipt_sha256 == equality.receipt_sha256
    assert operation.committed_staging_readback_count == 1
    assert operation.expected_unit_count == 1
    assert operation.ownership_observation_count == 1
    assert operation.ownership_partition_count == operation.projection_partition_count == 1
    assert operation.ownership_binding_count == operation.projection_item_count == 0
    assert operation.route_field_landing_count == 1
    assert operation.result_cell_row_count == 0
    assert operation.stats_lossless_row_count == 0
    assert operation.live_lossless_row_count == 0


def test_rectangular_stats_values_are_rebuilt_from_raw_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, expected_cells = _stats_case()
    values = _source_values(bundle)

    operation = _build_with_unrelated_staging_bypassed(monkeypatch, values)

    assert operation.result_cell_row_count == len(expected_cells) > 0
    assert operation.projection_item_count == len(expected_cells)
    assert operation.body_projection_policy_sha256 == (
        INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256
    )

    changed = dict(cast("tuple[dict[str, object], ...]", values["result_cell_rows"])[0])
    changed["canonical_json"] = "999"
    drifted = dict(values)
    drifted["result_cell_rows"] = (
        changed,
        *cast("tuple[dict[str, object], ...]", values["result_cell_rows"])[1:],
    )
    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ):
        _build_with_unrelated_staging_bypassed(monkeypatch, drifted)


def test_missing_result_closes_through_stats_lossless_without_fabricated_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, *_rest = _stats_fallback_bundle("missing_result")
    values = _source_values(bundle)

    operation = _build_with_unrelated_staging_bypassed(monkeypatch, values)

    assert operation.result_cell_row_count == 0
    assert operation.stats_lossless_row_count > 0
    assert operation.live_lossless_row_count == 0
    assert operation.expected_unit_count == 3
    assert operation.route_field_landing_count == 3
    assert operation.projection_item_count == operation.stats_lossless_row_count
    assert cast("tuple[dict[str, object], ...]", values["result_cell_rows"]) == ()


def test_live_response_closes_only_through_live_lossless_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _source_values(_live_bundle())

    operation = _build_with_unrelated_staging_bypassed(monkeypatch, values)

    assert operation.result_cell_row_count == 0
    assert operation.stats_lossless_row_count == 0
    assert operation.live_lossless_row_count > 0
    assert operation.expected_unit_count == 12
    assert operation.route_field_landing_count == 12
    assert operation.projection_item_count == operation.live_lossless_row_count


@pytest.mark.parametrize("authority_kind", ("policy", "declared-bodyless"))
def test_rejects_resealed_caller_selected_body_authorities(authority_kind: str) -> None:
    values = dict(_valid_values())
    body = cast("BodyValueProjectionReceiptV1", values["body_value_projection_receipt"])
    forged = _resealed_body_receipt(
        values,
        policy_sha256=(
            _sha("caller-selected-policy")
            if authority_kind == "policy"
            else body.body_projection_policy_sha256
        ),
        declared_bodyless_authority_sha256=(
            _sha("caller-selected-bodyless-authority")
            if authority_kind == "declared-bodyless"
            else body.declared_bodyless_authority_sha256
        ),
    )
    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ):
        _build(
            body_value_projection_receipt=forged,
            expected_body_value_projection_receipt_sha256=forged.receipt_sha256,
        )


def test_declared_packet_bytes_and_known_secrets_are_bounded_and_sanitized() -> None:
    with pytest.raises(W2OperationBuilderError, match="denominators differ"):
        _build(declared_bodyless_packet_bytes=(b"[]",))
    with pytest.raises(W2OperationBuilderError, match="bounded exact tuple"):
        _build(known_secrets=(b"x",) * 129)
    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ) as exc_info:
        _build(known_secrets=(b"{}",))
    assert "{}" not in str(exc_info.value)


def test_rejects_valid_but_foreign_independent_value_authority_witnesses() -> None:
    foreign_bundle, *_rest = _video_bundle("VideoDetails", {"future": [1]})
    foreign_result = build_independent_result_cell_authority(
        foreign_bundle,
        expected_raw_authority_bundle_sha256=foreign_bundle.bundle_sha256,
        declared_bodyless_packets=(),
        expected_declared_bodyless_packet_authority_sha256s=(),
        declared_bodyless_packet_bytes=(),
    )
    with pytest.raises(W2OperationBuilderError):
        _build(
            result_cell_authority_receipt=foreign_result,
            expected_result_cell_authority_sha256=foreign_result.authority_sha256,
        )

    stats_bundle, *_rest = _stats_fallback_bundle("additive_result")
    foreign_stats = build_independent_stats_lossless_authorities(
        stats_bundle,
        expected_raw_authority_bundle_sha256=stats_bundle.bundle_sha256,
    )
    assert foreign_stats
    with pytest.raises(W2OperationBuilderError):
        _build(
            stats_lossless_authorities=foreign_stats,
            expected_stats_lossless_authority_sha256s=tuple(
                item.receipt.authority_sha256 for item in foreign_stats
            ),
        )

    live_bundle = _live_bundle()
    foreign_live = build_live_lossless_value_authority(
        live_bundle,
        expected_raw_authority_bundle_sha256=live_bundle.bundle_sha256,
    )
    assert foreign_live.records
    with pytest.raises(W2OperationBuilderError):
        _build(
            live_lossless_authority=foreign_live,
            expected_live_lossless_authority_receipt_sha256=(foreign_live.receipt.receipt_sha256),
        )


def test_rejects_alias_returned_by_an_independent_child_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.contracts.w2_operation_builder as module

    values = dict(_valid_values())
    supplied = values["result_cell_authority_receipt"]
    monkeypatch.setattr(
        module,
        "build_independent_result_cell_authority",
        lambda *_args, **_kwargs: supplied,
    )

    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ):
        build_w2_operation(**values)


def test_rejects_result_authority_shallow_clone_with_caller_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.contracts.w2_operation_builder as module

    bundle, expected_cells = _stats_case()
    values = _source_values(bundle)
    supplied = cast("Any", values["result_cell_authority_receipt"])
    assert len(supplied.public_table_proof.cells) == len(expected_cells) > 0
    monkeypatch.setattr(
        module,
        "build_independent_result_cell_authority",
        lambda *_args, **_kwargs: copy(supplied),
    )

    with pytest.raises(W2OperationBuilderError, match="cross-authority reconstruction"):
        build_w2_operation(**values)


def test_rejects_stats_authority_shallow_clones_with_caller_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.contracts.w2_operation_builder as module

    bundle, *_rest = _stats_fallback_bundle("additive_result")
    values = _source_values(bundle)
    supplied = cast(
        "tuple[Any, ...]",
        values["stats_lossless_authorities"],
    )
    assert supplied and any(item.records for item in supplied)
    monkeypatch.setattr(
        module,
        "build_independent_stats_lossless_authorities",
        lambda *_args, **_kwargs: tuple(copy(item) for item in supplied),
    )

    with pytest.raises(W2OperationBuilderError, match="cross-authority reconstruction"):
        build_w2_operation(**values)


def test_rejects_live_authority_shallow_clone_with_caller_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.contracts.w2_operation_builder as module

    values = _source_values(_live_bundle())
    supplied = cast("Any", values["live_lossless_authority"])
    assert supplied.records
    monkeypatch.setattr(
        module,
        "build_live_lossless_value_authority",
        lambda *_args, **_kwargs: copy(supplied),
    )

    with pytest.raises(W2OperationBuilderError, match="cross-authority reconstruction"):
        build_w2_operation(**values)


def test_rejects_ownership_authority_assembled_from_caller_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.contracts.w2_operation_builder as module

    values = dict(_valid_values())
    supplied = LosslessOwnershipAuthorityV1(
        receipt=cast("Any", values["ownership_receipt"]),
        expected_unit_inventory=cast("Any", values["expected_unit_inventory"]),
        representation_assignments=cast("Any", values["representation_assignments"]),
        observations=cast("Any", values["ownership_observations"]),
        partitions=cast("Any", values["ownership_partitions"]),
        bindings=cast("Any", values["ownership_bindings"]),
    )
    monkeypatch.setattr(
        module,
        "build_public_value_ownership_authority",
        lambda *_args, **_kwargs: supplied,
    )

    with pytest.raises(W2OperationBuilderError, match="cross-authority reconstruction"):
        build_w2_operation(**values)


def test_rejects_projection_plan_shallow_clone_with_caller_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.contracts.w2_operation_builder as module

    values = dict(_valid_values())
    supplied = cast("Any", values["plan"])
    assert supplied.expected_units and supplied.observation_sources
    monkeypatch.setattr(
        module,
        "build_value_projection_plan",
        lambda *_args, **_kwargs: copy(supplied),
    )

    with pytest.raises(W2OperationBuilderError, match="cross-authority reconstruction"):
        build_w2_operation(**values)


def test_rejects_route_authority_with_replayed_receipt_and_caller_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.contracts.w2_operation_builder as module

    values = dict(_valid_values())
    receipt = RawNbaApiRouteFieldLandingAuthorityReceiptV1.from_row(
        cast("Any", values["route_field_landing_receipt"]).to_row()
    )
    rows = cast("Any", values["route_field_landing_authority_rows"])
    assert rows
    supplied = RawNbaApiRouteFieldLandingAuthorityV1(receipt=receipt, rows=rows)
    monkeypatch.setattr(
        module,
        "build_raw_nba_api_route_field_landing_authority",
        lambda **_kwargs: supplied,
    )

    with pytest.raises(W2OperationBuilderError, match="cross-authority reconstruction"):
        build_w2_operation(**values)


def test_public_projection_builder_consumes_rebuilt_rows_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.contracts.w2_operation_builder as module

    values = dict(_valid_values())
    original = module.build_public_table_value_projection

    def guarded(**kwargs: object) -> object:
        assert kwargs["value_representation_rows"] is not values["value_representation_rows"]
        assert kwargs["route_field_landing_rows"] is not values["route_field_landing_rows"]
        return original(**cast("Any", kwargs))

    monkeypatch.setattr(module, "build_public_table_value_projection", guarded)

    assert type(build_w2_operation(**values)) is W2OperationReceiptV1


def test_rejects_unowned_exact_static_packet_and_readback_bytes() -> None:
    static_bundle, *_rest = _static_bundle()
    observation = static_bundle.observations[0]
    packet, readback = _packet_source(observation)
    payload = _static_packet_bytes(observation.attempt.endpoint_id)

    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ):
        _build(
            declared_bodyless_packets=(packet,),
            expected_declared_bodyless_packet_authority_sha256s=(packet.packet_authority_sha256,),
            declared_bodyless_readback_receipts=(readback,),
            expected_declared_bodyless_readback_receipt_sha256s=(readback.receipt_sha256,),
            declared_bodyless_packet_bytes=(payload,),
        )


def test_external_pins_preflight_before_hostile_child_traversal() -> None:
    class Bomb:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(name)

    with pytest.raises(W2OperationBuilderError, match="lowercase SHA-256"):
        _build(
            expected_raw_authority_bundle_sha256="bad",
            raw_bundle=Bomb(),
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("body_value_projection_receipt", None),
        ("public_table_value_projection_receipt", None),
        ("expected_w2_operation_schema_sha256", True),
        ("raw_observations", []),
    ),
)
def test_rejects_foreign_exact_types_and_bool(
    field: str,
    replacement: object,
) -> None:
    values = _valid_values()
    if field == "body_value_projection_receipt":
        replacement = values["public_table_value_projection_receipt"]
    elif field == "public_table_value_projection_receipt":
        replacement = values["body_value_projection_receipt"]
    with pytest.raises(W2OperationBuilderError):
        _build(**{field: replacement})


def test_rejects_receipt_subclass_before_member_access() -> None:
    class HostileBodyReceipt(BodyValueProjectionReceiptV1):
        def to_row(self) -> dict[str, object]:
            raise AssertionError("subclass member was traversed")

    hostile = object.__new__(HostileBodyReceipt)
    with pytest.raises(W2OperationBuilderError, match="foreign exact type"):
        _build(body_value_projection_receipt=hostile)


def test_rejects_valid_shape_foreign_w2_schema_before_child_traversal() -> None:
    class Bomb:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(name)

    with pytest.raises(W2OperationBuilderError, match="public schema authority"):
        _build(
            expected_w2_operation_schema_sha256=_sha("foreign-w2-schema"),
            raw_bundle=Bomb(),
        )


def test_rejects_arbitrary_plan_relabel_and_raw_bundle_mismatch() -> None:
    plan = copy(_valid_values()["plan"])
    object.__setattr__(plan, "plan_sha256", _sha("relabelled-plan"))
    with pytest.raises(W2OperationBuilderError):
        _build(plan=plan, expected_plan_sha256=plan.plan_sha256)
    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ):
        _build(expected_raw_authority_bundle_sha256=_sha("foreign-bundle"))


def test_rejects_projection_child_mutation_duplication_and_alias() -> None:
    values = _valid_values()
    partition = copy(values["body_partitions"][0])
    object.__setattr__(partition, "fixed_zero_landing_sha256", _sha("foreign-fixed-zero"))
    with pytest.raises(W2OperationBuilderError):
        _build(body_partitions=(partition,))
    with pytest.raises(W2OperationBuilderError):
        _build(body_partitions=(values["body_partitions"][0],) * 2)
    with pytest.raises(W2OperationBuilderError, match="aliases"):
        _build(
            public_projection=values["body_projection"],
            public_partitions=values["body_partitions"],
            public_items=values["body_items"],
        )


def test_rejects_fully_resealed_equality_with_foreign_plan() -> None:
    equality = _valid_values()["value_projection_equality_receipt"]
    row = equality.to_row()
    row["plan_sha256"] = _sha("foreign-plan")
    row = _fully_reseal_receipt_row(row)
    receipt_sha256 = cast("str", row["receipt_sha256"])
    forged = ValueProjectionEqualityReceiptV1.from_row(
        row,
        expected_receipt_sha256=receipt_sha256,
    )
    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ):
        _build(
            value_projection_equality_receipt=forged,
            expected_value_projection_equality_receipt_sha256=receipt_sha256,
        )


def test_rejects_missing_duplicate_and_foreign_staging_readbacks() -> None:
    values = _valid_values()
    readback = values["committed_staging_readbacks"][0]
    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ):
        _build(
            committed_staging_readbacks=(),
            expected_committed_staging_readback_sha256s=(),
        )
    with pytest.raises(W2OperationBuilderError, match="duplicate identity"):
        _build(
            committed_staging_readbacks=(readback, readback),
            expected_committed_staging_readback_sha256s=(
                readback.readback_receipt_sha256,
                readback.readback_receipt_sha256,
            ),
        )
    foreign = copy(readback)
    object.__setattr__(foreign, "readback_receipt_sha256", _sha("foreign-readback"))
    with pytest.raises(W2OperationBuilderError):
        _build(
            committed_staging_readbacks=(foreign,),
            expected_committed_staging_readback_sha256s=(foreign.readback_receipt_sha256,),
        )


def test_hostile_child_cannot_spoof_a_trusted_builder_error() -> None:
    class HostileDigest:
        def __ne__(self, other: object) -> bool:
            raise W2OperationBuilderError("SECRET_CANARY")

    raw = copy(_valid_values()["raw_bundle"])
    object.__setattr__(raw, "bundle_sha256", HostileDigest())
    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ) as exc_info:
        _build(raw_bundle=raw)
    assert "SECRET_CANARY" not in str(exc_info.value)


def test_rejects_route_assignment_table_and_schema_drift() -> None:
    values = _valid_values()
    route_row = copy(values["route_field_landing_authority_rows"][0])
    object.__setattr__(route_row, "unit_sha256", _sha("foreign-unit"))
    with pytest.raises(W2OperationBuilderError):
        _build(route_field_landing_authority_rows=(route_row,))

    assignment = copy(values["representation_assignments"][0])
    object.__setattr__(assignment, "representation_kind", "response_lossless_records_v1")
    with pytest.raises(W2OperationBuilderError):
        _build(representation_assignments=(assignment,))

    rows = tuple(values["route_field_landing_rows"])
    with pytest.raises(W2OperationBuilderError):
        _build(route_field_landing_rows=rows + (dict(rows[0]),))
    with pytest.raises(W2OperationBuilderError):
        _build(result_cell_schema_sha256=_sha("foreign-result-schema"))


def test_rejects_resealed_route_aggregate_and_missing_source_receipts() -> None:
    values = _valid_values()
    receipt = values["route_field_landing_receipt"]
    forged_values = {
        key: value
        for key, value in receipt.to_row().items()
        if key not in {"schema_version", "receipt_sha256"}
    }
    forged_values["representation_assignment_root_sha256"] = _sha("foreign-assignment-root")
    forged = type(receipt).build(**forged_values)
    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ):
        _build(
            route_field_landing_receipt=forged,
            expected_route_field_landing_receipt_sha256=forged.receipt_sha256,
        )
    with pytest.raises(
        W2OperationBuilderError,
        match="failed exact cross-authority reconstruction",
    ):
        _build(route_landing_receipts=())


def test_operation_key_excludes_response_content_but_operation_binds_bundle() -> None:
    left, *_rest = _video_bundle("VideoDetails", {})
    right, *_rest = _video_bundle("VideoDetails", {"future": [1]})
    from nbadb.contracts.w2_operation import W2OperationKeyV1

    assert W2OperationKeyV1.build(left.observations).operation_key_sha256 == (
        W2OperationKeyV1.build(right.observations).operation_key_sha256
    )
    assert left.bundle_sha256 != right.bundle_sha256
    with pytest.raises(W2OperationBuilderError):
        _build(raw_bundle=right, raw_observations=right.observations)


def test_builder_dependency_and_linear_traversal_boundary() -> None:
    import nbadb.contracts.w2_operation_builder as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(
        name.startswith(
            (
                "nbadb.extract",
                "nbadb.kaggle",
                "nbadb.load",
                "polars",
                "pandera",
                "duckdb",
                "nba_api",
            )
        )
        for name in imports
    )
    assert {name for name in imports if name.startswith("nbadb.schemas")} == {
        "nbadb.schemas.raw.nba_api_w2_operation"
    }
    builder = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_w2_operation"
    )
    calls = [node for node in ast.walk(builder) if isinstance(node, ast.Call)]
    named_calls = {
        node.func.id: node.lineno
        for node in calls
        if isinstance(node.func, ast.Name)
        and node.func.id
        in {
            "build_independent_result_cell_authority",
            "build_independent_stats_lossless_authorities",
            "build_live_lossless_value_authority",
            "build_public_value_ownership_authority",
            "build_value_projection_plan",
            "build_independent_body_value_projection",
            "build_public_table_value_projection",
        }
    }
    assert tuple(named_calls) == (
        "build_independent_result_cell_authority",
        "build_independent_stats_lossless_authorities",
        "build_live_lossless_value_authority",
        "build_public_value_ownership_authority",
        "build_value_projection_plan",
        "build_independent_body_value_projection",
        "build_public_table_value_projection",
    )
    assert list(named_calls.values()) == sorted(named_calls.values())
    assert not any(
        isinstance(node.func, ast.Name) and node.func.id == "validate_raw_result_cell_authority"
        for node in calls
    )
    body_call = next(
        node
        for node in calls
        if isinstance(node.func, ast.Name)
        and node.func.id == "build_independent_body_value_projection"
    )
    body_keywords = {item.arg for item in body_call.keywords}
    assert {
        "body_blob_inventory",
        "expected_body_blob_inventory_sha256",
        "body_blob_inventory_readback_receipt",
        "expected_body_blob_inventory_readback_receipt_sha256",
        "declared_bodyless_packets",
        "declared_bodyless_readback_receipts",
        "declared_bodyless_packet_bytes",
        "known_secrets",
    } <= body_keywords
    assert not body_keywords & {
        "result_cell_rows",
        "stats_lossless_rows",
        "live_lossless_rows",
        "route_field_landing_rows",
        "committed_staging_readbacks",
    }
    public_call = next(
        node
        for node in calls
        if isinstance(node.func, ast.Name) and node.func.id == "build_public_table_value_projection"
    )
    public_keywords = {item.arg: item.value for item in public_call.keywords}
    for keyword, local_name in {
        "result_cell_rows": "exact_result_rows",
        "stats_lossless_rows": "exact_stats_rows",
        "live_lossless_rows": "exact_live_rows",
        "value_representation_rows": "exact_representation_rows",
        "route_field_landing_rows": "exact_route_rows",
    }.items():
        value = public_keywords[keyword]
        assert isinstance(value, ast.Name)
        assert value.id == local_name
    assert not any(isinstance(node.func, ast.Name) and node.func.id == "sorted" for node in calls)
    assert not any(
        isinstance(node.func, ast.Attribute) and node.func.attr in {"sort", "index", "count"}
        for node in calls
    )
