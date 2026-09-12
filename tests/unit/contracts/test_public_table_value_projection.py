"""Tests for the strict public-table-only W2 value projector."""

from __future__ import annotations

import ast
import hashlib
import json
from copy import copy
from dataclasses import fields
from functools import cache
from pathlib import Path
from typing import cast

import pytest

from nbadb.contracts.independent_stats_lossless_authority_builder import (
    build_independent_stats_lossless_authorities,
)
from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
    build_live_lossless_value_authority,
)
from nbadb.contracts.public_table_value_projection import (
    RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
    RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
    RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
    PublicTableValueProjectionError,
    PublicTableValueProjectionReceiptV1,
    PublicTableValueProjectionV1,
    build_public_table_value_projection,
)
from nbadb.contracts.route_field_landing_authority import RawNbaApiRouteFieldLandingV1
from nbadb.contracts.stats_lossless_value_authority import (
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
)
from nbadb.contracts.value_projection import (
    ValueProjectionItemV1,
    ValueProjectionPartitionV1,
    ValueProjectionReceiptV1,
)
from nbadb.contracts.value_projection_plan import ValueProjectionPlanV1
from nbadb.contracts.value_projection_plan_builder import build_value_projection_plan
from tests.unit.contracts.test_public_value_authority_adapter import (
    _live_bundle,
    _stats_authority,
)
from tests.unit.contracts.test_raw_request_authority import (
    _stats_fallback_bundle,
    _video_bundle,
)
from tests.unit.contracts.test_raw_result_cell_authority import _stats_case
from tests.unit.contracts.test_value_projection_plan_builder import (
    _fixture as _plan_fixture,
)
from tests.unit.contracts.test_value_projection_plan_builder import (
    _zero_row_nonempty_header_bundle,
)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _project(
    plan: ValueProjectionPlanV1,
    *,
    cells: tuple[object, ...] = (),
    stats_rows: tuple[object, ...] = (),
    live_rows: tuple[object, ...] = (),
    assignment_rows: tuple[object, ...] | None = None,
    route_rows: tuple[object, ...] | None = None,
    **changes: object,
) -> PublicTableValueProjectionV1:
    values: dict[str, object] = {
        "plan": plan,
        "expected_plan_sha256": plan.plan_sha256,
        "expected_raw_authority_bundle_sha256": plan.raw_authority_bundle_sha256,
        "expected_ownership_receipt_sha256": plan.ownership_receipt_sha256,
        "result_cell_schema_sha256": RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
        "result_cell_rows": cells,
        "stats_lossless_schema_sha256": STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
        "stats_lossless_rows": stats_rows,
        "live_lossless_schema_sha256": LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        "live_lossless_rows": live_rows,
        "value_representation_schema_sha256": (RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256),
        "value_representation_rows": (
            tuple(item.to_row() for item in plan.assignments)
            if assignment_rows is None
            else assignment_rows
        ),
        "route_field_landing_schema_sha256": RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
        "route_field_landing_rows": (
            tuple(
                _route_row(
                    plan,
                    unit_ordinal=ordinal,
                    landing_field_ordinal=ordinal,
                )
                for ordinal in range(plan.expected_unit_count)
            )
            if route_rows is None
            else route_rows
        ),
    }
    values.update(changes)
    return build_public_table_value_projection(**values)


def _route_row(
    plan: ValueProjectionPlanV1,
    *,
    unit_ordinal: int = 0,
    landing_field_ordinal: int = 0,
) -> dict[str, object]:
    unit = plan.expected_units[unit_ordinal]
    assignment = next(item for item in plan.assignments if item.unit_sha256 == unit.unit_sha256)
    return RawNbaApiRouteFieldLandingV1.build(
        landing_field_ordinal=landing_field_ordinal,
        route_receipt_ordinal=0,
        raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
        route_landing_receipt_sha256="a" * 64,
        raw_route_landing_sha256="b" * 64,
        observation_sha256=unit.observation_sha256,
        route_ordinal=0,
        route_id="public_projection_route",
        staging_key="raw_public_projection",
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
    ).to_row()


def _reseal_assignment_row(row: dict[str, object]) -> dict[str, object]:
    changed = dict(row)
    changed["assignment_sha256"] = _canonical_sha256(
        {
            "schema_version": 1,
            "kind": "nbadb_value_representation_assignment_v1",
            **{
                name: value
                for name, value in changed.items()
                if name not in {"schema_version", "assignment_sha256"}
            },
        }
    )
    return changed


def _reseal_route_row(row: dict[str, object]) -> dict[str, object]:
    changed = dict(row)
    changed["landing_field_sha256"] = _canonical_sha256(
        {
            "kind": "raw_nba_api_route_field_landing_v1",
            **{name: value for name, value in changed.items() if name != "landing_field_sha256"},
        }
    )
    return changed


def _reseal_result_row(row: dict[str, object]) -> dict[str, object]:
    changed = dict(row)
    changed["cell_sha256"] = _canonical_sha256(
        {
            "schema_version": 2,
            "kind": "raw_nba_api_result_cell_v2",
            **{
                name: value
                for name, value in changed.items()
                if name not in {"schema_version", "cell_sha256"}
            },
        }
    )
    return changed


@cache
def _rectangular_fixture() -> tuple[ValueProjectionPlanV1, tuple[dict[str, object], ...]]:
    bundle, cells = _stats_case()
    plan = build_value_projection_plan(**_plan_fixture(bundle=bundle, cells=cells))
    return plan, tuple(item.to_row() for item in cells)


@cache
def _residual_fixture() -> tuple[ValueProjectionPlanV1, tuple[dict[str, object], ...]]:
    bundle, observation, _occurrences, _landings = _video_bundle(
        "VideoDetails",
        {"future": [None, {}, [], "\u2603", 9_007_199_254_740_991]},
    )
    stats = _stats_authority(bundle, observation, include_response_residual=True)
    plan = build_value_projection_plan(**_plan_fixture(bundle=bundle, cells=(), stats=(stats,)))
    return plan, tuple(item.to_row() for item in stats.records)


@cache
def _live_fixture() -> tuple[ValueProjectionPlanV1, tuple[dict[str, object], ...]]:
    bundle = _live_bundle()
    live = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    plan = build_value_projection_plan(**_plan_fixture(bundle=bundle, cells=(), live=live))
    return plan, tuple(item.to_row() for item in live.records)


@cache
def _fixed_zero_fixture() -> ValueProjectionPlanV1:
    bundle, _observation, _occurrences, _landings = _video_bundle("VideoDetails", {})
    return build_value_projection_plan(**_plan_fixture(bundle=bundle, cells=()))


@cache
def _missing_expected_stats_fixture() -> tuple[
    ValueProjectionPlanV1,
    tuple[dict[str, object], ...],
]:
    bundle, _observation, _occurrences, _landings = _stats_fallback_bundle("missing_result")
    stats = build_independent_stats_lossless_authorities(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    plan = build_value_projection_plan(
        **_plan_fixture(bundle=bundle, cells=(), stats=cast("object", stats))
    )
    return plan, tuple(row for authority in stats for row in authority.public_rows())


def test_rectangular_public_rows_build_exact_projection_and_receipt() -> None:
    plan, cells = _rectangular_fixture()
    authority = _project(plan, cells=cast("tuple[object, ...]", cells))

    assert type(authority) is PublicTableValueProjectionV1
    assert type(authority.projection) is ValueProjectionReceiptV1
    assert all(type(item) is ValueProjectionPartitionV1 for item in authority.partitions)
    assert all(type(item) is ValueProjectionItemV1 for item in authority.items)
    assert authority.receipt.result_cell_row_count == len(cells)
    assert authority.receipt.value_representation_row_count == plan.assignment_count
    assert authority.receipt.route_field_landing_row_count == plan.expected_unit_count
    assert authority.projection.rectangular_result_item_count == len(cells)
    assert authority.projection.item_count == plan.source_record_count
    assert authority.projection.partition_count == plan.partition_count


def test_missing_expected_stats_result_uses_exact_expected_ordinal_path() -> None:
    plan, rows = _missing_expected_stats_fixture()
    planned = next(item for item in plan.occurrence_plans if item.result_presence == "missing")
    authority = _project(plan, stats_rows=cast("tuple[object, ...]", rows))
    partition = next(
        item for item in authority.partitions if item.occurrence_sha256 == planned.occurrence_sha256
    )
    expected_path = f"$.expectedResults[{planned.expected_result_ordinal}]"

    assert planned.result_path is None
    assert planned.provider_result_ordinal is None
    assert planned.canonical_result_ordinal is None
    assert planned.expected_result_ordinal is not None
    assert partition.result_path == expected_path
    assert all(
        item.coordinate()["result_path"] == expected_path
        for item in authority.items[
            partition.first_global_item_ordinal : partition.first_global_item_ordinal
            + partition.item_count
        ]
    )


def test_receipt_has_exact_canonical_replay_and_no_value_payload() -> None:
    plan, cells = _rectangular_fixture()
    receipt = _project(plan, cells=cast("tuple[object, ...]", cells)).receipt
    encoded = receipt.canonical_bytes()

    assert PublicTableValueProjectionReceiptV1.from_canonical_bytes(encoded) == receipt
    assert PublicTableValueProjectionReceiptV1.from_row(receipt.to_row()) == receipt
    assert b"canonical_json" not in encoded
    assert b"payload_json" not in encoded
    assert b"field_name" not in encoded
    assert b"source_record" not in encoded


@pytest.mark.parametrize("mode", ("missing", "duplicate", "reordered", "resealed"))
def test_value_representation_rows_equal_the_plan_exactly(mode: str) -> None:
    plan, cells = _rectangular_fixture()
    rows = [item.to_row() for item in plan.assignments]
    if mode == "missing":
        rows.pop()
    elif mode == "duplicate":
        rows[1] = dict(rows[0])
    elif mode == "reordered":
        rows[0], rows[1] = rows[1], rows[0]
    else:
        rows[0]["representation_kind"] = "stats_lossless_records_v1"
        rows[0] = _reseal_assignment_row(rows[0])

    with pytest.raises(PublicTableValueProjectionError, match="exact ordered plan"):
        _project(
            plan,
            cells=cast("tuple[object, ...]", cells),
            assignment_rows=tuple(rows),
        )


def test_route_field_rows_bind_exact_plan_units_and_receipt_root() -> None:
    plan, cells = _rectangular_fixture()
    route_rows = tuple(
        _route_row(plan, unit_ordinal=ordinal, landing_field_ordinal=ordinal)
        for ordinal in range(plan.expected_unit_count)
    )
    authority = _project(
        plan,
        cells=cast("tuple[object, ...]", cells),
        route_rows=route_rows,
    )

    assert authority.receipt.route_field_landing_row_count == len(route_rows)
    assert authority.receipt.route_field_landing_row_root_sha256 != "0" * 64
    assert authority.receipt.value_representation_row_count == plan.assignment_count


@pytest.mark.parametrize(
    "mode",
    (
        "duplicate",
        "semantic_duplicate",
        "missing_unit",
        "sparse",
        "cross_observation",
        "foreign_unit",
        "bundle_drift",
    ),
)
def test_route_field_rows_reject_duplicate_sparse_or_foreign_closure(mode: str) -> None:
    plan, cells = _rectangular_fixture()
    row = _route_row(plan)
    rows: tuple[object, ...]
    if mode == "duplicate":
        rows = (row, dict(row))
    elif mode == "semantic_duplicate":
        repeated = dict(row)
        repeated["landing_field_ordinal"] = 1
        rows = (row, _reseal_route_row(repeated))
    elif mode == "missing_unit":
        rows = (row,)
    else:
        changed = dict(row)
        if mode == "sparse":
            changed["landing_field_ordinal"] = 1
        elif mode == "cross_observation":
            changed["observation_sha256"] = "f" * 64
        elif mode == "foreign_unit":
            changed["unit_sha256"] = "f" * 64
            changed["assignment_sha256"] = _canonical_sha256(
                {
                    "schema_version": 1,
                    "kind": "nbadb_value_representation_assignment_v1",
                    "raw_authority_bundle_sha256": changed["raw_authority_bundle_sha256"],
                    "unit_sha256": changed["unit_sha256"],
                    "unit_ordinal": changed["unit_ordinal"],
                    "source_input_kind": changed["source_input_kind"],
                    "representation_kind": changed["representation_kind"],
                }
            )
        else:
            changed["raw_authority_bundle_sha256"] = "f" * 64
            changed["assignment_sha256"] = _canonical_sha256(
                {
                    "schema_version": 1,
                    "kind": "nbadb_value_representation_assignment_v1",
                    "raw_authority_bundle_sha256": changed["raw_authority_bundle_sha256"],
                    "unit_sha256": changed["unit_sha256"],
                    "unit_ordinal": changed["unit_ordinal"],
                    "source_input_kind": changed["source_input_kind"],
                    "representation_kind": changed["representation_kind"],
                }
            )
        rows = (_reseal_route_row(changed),)

    with pytest.raises(PublicTableValueProjectionError):
        _project(
            plan,
            cells=cast("tuple[object, ...]", cells),
            route_rows=rows,
        )


def test_route_field_rows_reject_hostile_shape_subclass_and_secret_name() -> None:
    plan, cells = _rectangular_fixture()
    row = _route_row(plan)
    hostile = dict(row)
    hostile.update(
        {
            "row_kind": "field_binding",
            "field_ordinal": 0,
            "field_name": "authorization_bearer_secret_token",
            "field_authority_sha256": "c" * 64,
            "field_origin": "provider_bound",
            "logical_type_sha256": "d" * 64,
        }
    )

    class ForeignRow(dict[str, object]):
        pass

    with pytest.raises(PublicTableValueProjectionError, match="public-safe"):
        _project(
            plan,
            cells=cast("tuple[object, ...]", cells),
            route_rows=(_reseal_route_row(hostile),),
        )
    with pytest.raises(PublicTableValueProjectionError, match="exact built-in dict"):
        _project(
            plan,
            cells=cast("tuple[object, ...]", cells),
            route_rows=(ForeignRow(row),),
        )


def test_stats_residual_projects_its_exact_public_record_inventory() -> None:
    plan, rows = _residual_fixture()
    authority = _project(plan, stats_rows=cast("tuple[object, ...]", rows))

    assert authority.projection.positive_response_residual_partition_count == 1
    assert authority.projection.response_lossless_item_count == len(rows)
    states = {item.value_state for item in authority.items}
    assert "absent" in states
    assert "canonical" in states
    assert any(
        item.value_kind == "integer" and item.canonical_json == "7" for item in authority.items
    )


def test_live_public_rows_project_occurrences_nodes_fields_and_residual() -> None:
    plan, rows = _live_fixture()
    authority = _project(plan, live_rows=cast("tuple[object, ...]", rows))

    assert authority.receipt.live_lossless_row_count == len(rows)
    assert authority.projection.live_lossless_item_count > 0
    assert authority.projection.response_lossless_item_count > 0
    assert {item.record_kind for item in authority.items} >= {
        "result_declaration",
        "result_occurrence",
        "node",
        "field_cell",
    }
    assert all(
        item.coordinate()["matches_result_occurrence"] is not None
        for item in authority.items
        if item.record_kind == "node" and item.representation_kind == "live_lossless_nodes_v1"
    )


def test_fixed_zero_is_explicit_without_fabricated_public_item() -> None:
    plan = _fixed_zero_fixture()
    authority = _project(plan)

    assert authority.items == ()
    assert len(authority.partitions) == 1
    assert authority.partitions[0].partition_kind == "response_fixed_zero"
    assert authority.partitions[0].fixed_zero_landing_sha256 is not None
    assert authority.projection.fixed_zero_partition_count == 1
    assert authority.projection.response_fixed_zero_item_count == 0


def test_zero_row_nonempty_headers_remain_in_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _zero_row_nonempty_header_bundle(monkeypatch)
    plan = build_value_projection_plan(**_plan_fixture(bundle=bundle, cells=()))
    authority = _project(plan)
    result_partitions = tuple(
        item for item in authority.partitions if item.partition_kind == "result_occurrence"
    )

    assert result_partitions
    assert all(item.row_count == 0 and item.item_count == 0 for item in result_partitions)
    assert all(item.header_count > 0 for item in result_partitions)
    assert tuple(item.ordered_headers_json for item in result_partitions) == tuple(
        item.ordered_headers_json for item in plan.occurrence_plans
    )


@pytest.mark.parametrize("mode", ("missing", "extra", "duplicate", "reordered"))
def test_result_public_rows_require_exact_one_to_one_order(mode: str) -> None:
    plan, exact = _rectangular_fixture()
    rows = list(exact)
    if mode == "missing":
        rows.pop()
    elif mode == "extra":
        rows.append(dict(rows[-1]))
    elif mode == "duplicate":
        rows[1] = dict(rows[0])
    else:
        rows[0], rows[1] = rows[1], rows[0]

    with pytest.raises(
        PublicTableValueProjectionError, match="missing|foreign|duplicated|reordered"
    ):
        _project(plan, cells=tuple(rows))


def test_coordinated_result_row_reseal_cannot_cross_observation() -> None:
    plan, exact = _rectangular_fixture()
    row = dict(exact[0])
    row["observation_sha256"] = "0" * 64

    with pytest.raises(PublicTableValueProjectionError):
        _project(plan, cells=(_reseal_result_row(row), *exact[1:]))


@pytest.mark.parametrize("mode", ("secret_header", "secret_value", "secret_object_key"))
def test_result_public_rows_reject_coordinated_secret_reseals(mode: str) -> None:
    plan, exact = _rectangular_fixture()
    row = dict(exact[0])
    if mode == "secret_header":
        row["header_name"] = "AccessToken"
    else:
        value = (
            "Bearer abcdefghijklmnopqrstuvwxyz"
            if mode == "secret_value"
            else {"clientSecret": "redacted"}
        )
        canonical_json = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        row["canonical_json"] = canonical_json
        row["canonical_json_sha256"] = hashlib.sha256(canonical_json.encode()).hexdigest()
        row["presence_kind"] = "present"
        row["value_kind"] = "string" if type(value) is str else "object"
    with pytest.raises(PublicTableValueProjectionError, match="public-safe|secret|sensitive"):
        _project(plan, cells=(_reseal_result_row(row), *exact[1:]))


def test_schema_and_plan_pins_fail_before_hostile_row_traversal() -> None:
    plan, _cells = _rectangular_fixture()

    class Bomb:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(name)

    with pytest.raises(PublicTableValueProjectionError, match="external pins"):
        _project(
            plan,
            cells=(Bomb(),),
            expected_plan_sha256="0" * 64,
        )
    with pytest.raises(PublicTableValueProjectionError, match="frozen exact contract"):
        _project(
            plan,
            cells=(Bomb(),),
            result_cell_schema_sha256="0" * 64,
        )
    with pytest.raises(PublicTableValueProjectionError, match="frozen exact contract"):
        _project(
            plan,
            cells=(Bomb(),),
            value_representation_schema_sha256="0" * 64,
        )
    with pytest.raises(PublicTableValueProjectionError, match="frozen exact contract"):
        _project(
            plan,
            cells=(Bomb(),),
            route_field_landing_schema_sha256="0" * 64,
        )


def test_exact_types_reject_bool_tuple_subclass_and_plan_subclass() -> None:
    plan, cells = _rectangular_fixture()

    class ForeignTuple(tuple[object, ...]):
        pass

    class ForeignPlan(ValueProjectionPlanV1):
        pass

    with pytest.raises(PublicTableValueProjectionError, match="lowercase full SHA"):
        _project(plan, cells=cast("tuple[object, ...]", cells), expected_plan_sha256=True)
    with pytest.raises(PublicTableValueProjectionError, match="foreign or over-bound"):
        _project(plan, cells=ForeignTuple(cells))
    hostile = ForeignPlan(**{item.name: getattr(plan, item.name) for item in fields(plan)})
    with pytest.raises(PublicTableValueProjectionError, match="foreign exact DTO"):
        _project(hostile, cells=cast("tuple[object, ...]", cells))


def test_receipt_rejects_reordered_subclass_bool_and_noncanonical_bytes() -> None:
    plan, cells = _rectangular_fixture()
    receipt = _project(plan, cells=cast("tuple[object, ...]", cells)).receipt
    reversed_row = dict(reversed(tuple(receipt.to_row().items())))
    with pytest.raises(PublicTableValueProjectionError, match="ordered shape"):
        PublicTableValueProjectionReceiptV1.from_row(reversed_row)

    row = receipt.to_row()
    row["projection_item_count"] = True
    with pytest.raises(PublicTableValueProjectionError, match="exact integer"):
        PublicTableValueProjectionReceiptV1.from_row(row)

    pretty = json.dumps(receipt.to_row(), ensure_ascii=False, indent=2, sort_keys=True).encode()
    with pytest.raises(PublicTableValueProjectionError, match="canonical byte form"):
        PublicTableValueProjectionReceiptV1.from_canonical_bytes(pretty)


def test_aggregate_rejects_reordered_or_post_construction_corrupted_children() -> None:
    plan, cells = _rectangular_fixture()
    authority = _project(plan, cells=cast("tuple[object, ...]", cells))

    with pytest.raises(PublicTableValueProjectionError):
        PublicTableValueProjectionV1(
            receipt=authority.receipt,
            projection=authority.projection,
            partitions=authority.partitions,
            items=tuple(reversed(authority.items)),
        )

    corrupted = copy(authority.items[0])
    object.__setattr__(corrupted, "global_item_ordinal", 1)
    with pytest.raises(PublicTableValueProjectionError, match="exact replay"):
        PublicTableValueProjectionV1(
            receipt=authority.receipt,
            projection=authority.projection,
            partitions=authority.partitions,
            items=(corrupted, *authority.items[1:]),
        )


def test_result_row_rejects_deep_duplicate_key_and_oversized_integer() -> None:
    plan, exact = _rectangular_fixture()
    base = dict(exact[0])
    hostile_values = (
        "[" * 10_000 + "0" + "]" * 10_000,
        '{"a":1,"a":2}',
        str(1 << 128),
    )
    for canonical_json in hostile_values:
        row = dict(base)
        row["canonical_json"] = canonical_json
        row["canonical_json_sha256"] = hashlib.sha256(canonical_json.encode()).hexdigest()
        with pytest.raises(PublicTableValueProjectionError):
            _project(plan, cells=(row, *exact[1:]))


def test_public_projector_dependency_purity_and_linear_shape() -> None:
    path = Path("src/nbadb/contracts/public_table_value_projection.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = (
        "nbadb.extract",
        "nbadb.orchestrate",
        "nbadb.schemas",
        "nbadb.kaggle",
        "nbadb.contracts.body",
        "nbadb.contracts.declared_bodyless",
        "nbadb.contracts.raw_request",
        "polars",
        "pandera",
        "nba_api",
    )
    imports: list[str] = []
    attribute_calls: list[str] = []
    name_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attribute_calls.append(node.func.attr)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name_calls.append(node.func.id)
    assert not any(name.startswith(forbidden) for name in imports)
    assert not ({"count", "index", "sort"} & set(attribute_calls))
    builder = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_public_table_value_projection"
    )
    builder_name_calls = {
        node.func.id
        for node in ast.walk(builder)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "sorted" not in builder_name_calls


def test_live_and_stats_rows_cannot_be_dual_or_cross_relation_sources() -> None:
    live_plan, live_rows = _live_fixture()
    with pytest.raises(PublicTableValueProjectionError):
        _project(live_plan, stats_rows=cast("tuple[object, ...]", live_rows))

    stats_plan, stats_rows = _residual_fixture()
    with pytest.raises(PublicTableValueProjectionError):
        _project(stats_plan, live_rows=cast("tuple[object, ...]", stats_rows))


def test_corrupted_exact_public_child_exception_is_normalized() -> None:
    plan, rows = _live_fixture()
    first = copy(rows[0])
    first["payload_json"] = object()
    with pytest.raises(PublicTableValueProjectionError) as caught:
        _project(plan, live_rows=(first, *rows[1:]))
    assert caught.value.__cause__ is None
