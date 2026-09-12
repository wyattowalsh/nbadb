"""Focused tests for the separately sealed value-projection equality receipt."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from nbadb.contracts.value_projection import (
    ValueProjectionItemV1,
    ValueProjectionPartitionV1,
    ValueProjectionReceiptV1,
)
from nbadb.contracts.value_projection_equality import (
    ValueProjectionEqualityError,
    ValueProjectionEqualityReceiptV1,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha(value: object) -> str:
    if type(value) is str:
        value = value.encode("utf-8")
    if type(value) is not bytes:
        value = _canonical(value)
    return hashlib.sha256(value).hexdigest()


def _ordered_root(*, kind: str, bundle: str, items: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(b"nbadb-value-projection-length-framed-root-v1\x00")

    def feed(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, byteorder="big", signed=False))
        digest.update(value)

    feed(b"1")
    feed(kind.encode("utf-8"))
    feed(bundle.encode("ascii"))
    feed(str(len(items)).encode("ascii"))
    for ordinal, identity in enumerate(items):
        feed(str(ordinal).encode("ascii"))
        feed(identity.encode("ascii"))
    return digest.hexdigest()


def _fully_reseal_receipt_row(row: dict[str, object]) -> dict[str, object]:
    resealed = dict(row)
    bundle = resealed["raw_authority_bundle_sha256"]
    assert type(bundle) is str
    child_roots = (
        resealed["body_input_root_sha256"],
        resealed["public_input_root_sha256"],
        resealed["partition_equality_root_sha256"],
        resealed["item_equality_root_sha256"],
    )
    assert all(isinstance(item, str) for item in child_roots)
    resealed["equality_root_sha256"] = _ordered_root(
        kind="nbadb_value_projection_equality_roots_v1",
        bundle=bundle,
        items=tuple(child_roots),
    )
    identity = {
        "schema_version": 1,
        "kind": ValueProjectionEqualityReceiptV1.kind,
        **{
            item.name: resealed[item.name]
            for item in fields(ValueProjectionEqualityReceiptV1)
            if item.name != "receipt_sha256"
        },
    }
    resealed["receipt_sha256"] = _sha(identity)
    return resealed


def _assert_resealed_receipt_rejected(
    row: dict[str, object],
    *,
    match: str,
) -> None:
    resealed = _fully_reseal_receipt_row(row)
    expected = resealed["receipt_sha256"]
    assert type(expected) is str
    with pytest.raises(ValueProjectionEqualityError, match=match):
        ValueProjectionEqualityReceiptV1.from_row(
            resealed,
            expected_receipt_sha256=expected,
        )
    with pytest.raises(ValueProjectionEqualityError, match=match):
        ValueProjectionEqualityReceiptV1.from_canonical_bytes(
            _canonical(resealed),
            expected_receipt_sha256=expected,
        )


def _legacy_root(kind: str) -> str:
    return _sha(
        {
            "schema_version": 1,
            "kind": kind,
            "count": 0,
            "items": [],
        }
    )


def _empty_projection() -> tuple[ValueProjectionReceiptV1, str, str]:
    bundle = _sha("equality-bundle")
    expected_unit_root = _sha(
        {
            "schema_version": 1,
            "kind": "nbadb_expected_value_unit_ordered_root_v1",
            "raw_authority_bundle_sha256": bundle,
            "count": 0,
            "items": [],
        }
    )
    inventory_sha256 = _sha(
        {
            "kind": "nbadb_expected_value_unit_inventory_v1",
            "schema_version": 1,
            "raw_authority_bundle_sha256": bundle,
            "unit_count": 0,
            "unit_root_sha256": expected_unit_root,
            "units": [],
        }
    )
    ownership_values = {
        "raw_authority_bundle_sha256": bundle,
        "expected_unit_count": 0,
        "expected_unit_inventory_sha256": inventory_sha256,
        "expected_unit_root_sha256": expected_unit_root,
        "representation_assignment_count": 0,
        "representation_assignment_root_sha256": _legacy_root(
            "nbadb_lossless_representation_assignments_v1"
        ),
        "observation_count": 0,
        "observation_root_sha256": _legacy_root("nbadb_lossless_owned_observations_v1"),
        "partition_count": 0,
        "partition_root_sha256": _legacy_root("nbadb_lossless_ownership_partitions_v1"),
        "result_occurrence_partition_count": 0,
        "zero_result_occurrence_partition_count": 0,
        "result_occurrence_record_count": 0,
        "response_residual_partition_count": 0,
        "positive_response_residual_partition_count": 0,
        "zero_response_residual_partition_count": 0,
        "response_residual_record_count": 0,
        "response_fixed_zero_partition_count": 0,
        "fixed_zero_landing_root_sha256": _legacy_root("nbadb_lossless_fixed_zero_landings_v1"),
        "binding_count": 0,
        "binding_root_sha256": _legacy_root("nbadb_lossless_ownership_bindings_v1"),
        "source_record_count": 0,
        "source_record_root_sha256": _legacy_root("nbadb_lossless_owned_source_records_v1"),
    }
    ownership_sha256 = _sha(
        {
            "schema_version": 1,
            "kind": "nbadb_lossless_ownership_receipt_v1",
            **ownership_values,
        }
    )
    ownership_row = {
        "schema_version": 1,
        "receipt_sha256": ownership_sha256,
        **ownership_values,
    }
    projection = ValueProjectionReceiptV1.build(
        raw_authority_bundle_sha256=bundle,
        ownership_receipt_row=ownership_row,
        expected_unit_rows=(),
        representation_assignment_rows=(),
        ownership_observation_rows=(),
        ownership_partition_rows=(),
        ownership_binding_rows=(),
        partitions=(),
        items=(),
    )
    return projection, bundle, ownership_sha256


def _build_values() -> dict[str, Any]:
    projection, bundle, ownership = _empty_projection()
    return {
        "expected_raw_authority_bundle_sha256": bundle,
        "expected_ownership_receipt_sha256": ownership,
        "expected_plan_sha256": _sha("projection-plan"),
        "body_projection": ValueProjectionReceiptV1.from_row(projection.to_row()),
        "expected_body_projection_sha256": projection.projection_sha256,
        "body_partitions": (),
        "body_items": (),
        "public_projection": ValueProjectionReceiptV1.from_row(projection.to_row()),
        "expected_public_projection_sha256": projection.projection_sha256,
        "public_partitions": (),
        "public_items": (),
    }


def _nonempty_build_values() -> dict[str, Any]:
    from tests.unit.contracts.test_value_projection import _complete_projection

    projection, partitions, items, _authority = _complete_projection()
    return {
        "expected_raw_authority_bundle_sha256": projection.raw_authority_bundle_sha256,
        "expected_ownership_receipt_sha256": projection.ownership_receipt_sha256,
        "expected_plan_sha256": _sha("nonempty-projection-plan"),
        "body_projection": ValueProjectionReceiptV1.from_row(projection.to_row()),
        "expected_body_projection_sha256": projection.projection_sha256,
        "body_partitions": tuple(
            ValueProjectionPartitionV1.from_row(item.to_row()) for item in partitions
        ),
        "body_items": tuple(ValueProjectionItemV1.from_row(item.to_row()) for item in items),
        "public_projection": ValueProjectionReceiptV1.from_row(projection.to_row()),
        "expected_public_projection_sha256": projection.projection_sha256,
        "public_partitions": tuple(
            ValueProjectionPartitionV1.from_row(item.to_row()) for item in partitions
        ),
        "public_items": tuple(ValueProjectionItemV1.from_row(item.to_row()) for item in items),
    }


def _item_with_value(item: ValueProjectionItemV1, value: object) -> ValueProjectionItemV1:
    return ValueProjectionItemV1.build(
        raw_authority_bundle_sha256=item.raw_authority_bundle_sha256,
        ownership_binding_sha256=item.ownership_binding_sha256,
        ownership_binding_ordinal=item.ownership_binding_ordinal,
        source_record_sha256=item.source_record_sha256,
        observation_record_sha256=item.observation_record_sha256,
        observation_sha256=item.observation_sha256,
        observation_ordinal=item.observation_ordinal,
        ownership_partition_sha256=item.ownership_partition_sha256,
        partition_ordinal=item.partition_ordinal,
        unit_sha256=item.unit_sha256,
        unit_ordinal=item.unit_ordinal,
        assignment_sha256=item.assignment_sha256,
        source_input_kind=item.source_input_kind,
        representation_kind=item.representation_kind,
        unit_kind=item.unit_kind,
        occurrence_sha256=item.occurrence_sha256,
        occurrence_ordinal=item.occurrence_ordinal,
        global_item_ordinal=item.global_item_ordinal,
        partition_item_ordinal=item.partition_item_ordinal,
        record_kind=item.record_kind,
        coordinate=item.coordinate(),
        value=value,
    )


def test_equal_projection_rows_seal_and_replay() -> None:
    receipt = ValueProjectionEqualityReceiptV1.build(**_build_values())

    assert receipt.body_projection_sha256 == receipt.public_projection_sha256
    assert receipt.partition_equality_count == 0
    assert receipt.item_equality_count == 0
    assert receipt.body_input_count == receipt.public_input_count == 1
    assert receipt.body_input_root_sha256 != receipt.public_input_root_sha256
    assert (
        ValueProjectionEqualityReceiptV1.from_row(
            receipt.to_row(),
            expected_receipt_sha256=receipt.receipt_sha256,
        )
        == receipt
    )

    nonempty = ValueProjectionEqualityReceiptV1.build(**_nonempty_build_values())
    assert nonempty.body_input_count == nonempty.public_input_count
    assert nonempty.body_input_count == (
        1 + nonempty.partition_equality_count + nonempty.item_equality_count
    )
    assert (
        ValueProjectionEqualityReceiptV1.from_canonical_bytes(
            receipt.canonical_bytes(),
            expected_receipt_sha256=receipt.receipt_sha256,
        )
        == receipt
    )


def test_projection_pin_mismatch_and_self_alias_fail_closed() -> None:
    values = _build_values()
    values["expected_public_projection_sha256"] = _sha("foreign-projection")
    with pytest.raises(ValueProjectionEqualityError, match="external authority pins"):
        ValueProjectionEqualityReceiptV1.build(**values)


def test_missing_reordered_and_value_mismatch_fail_closed() -> None:
    missing = _nonempty_build_values()
    missing["public_items"] = missing["public_items"][:-1]
    with pytest.raises(ValueProjectionEqualityError, match="item count"):
        ValueProjectionEqualityReceiptV1.build(**missing)

    reordered = _nonempty_build_values()
    reordered["public_items"] = tuple(reversed(reordered["public_items"]))
    with pytest.raises(ValueProjectionEqualityError, match="item root"):
        ValueProjectionEqualityReceiptV1.build(**reordered)

    changed = _nonempty_build_values()
    public_items = changed["public_items"]
    assert type(public_items) is tuple
    changed["public_items"] = (
        _item_with_value(public_items[0], "independently-different"),
        *public_items[1:],
    )
    with pytest.raises(ValueProjectionEqualityError, match="item root"):
        ValueProjectionEqualityReceiptV1.build(**changed)


def test_foreign_child_subclass_and_bool_pin_fail_before_comparison() -> None:
    values = _nonempty_build_values()
    foreign_type = type("ForeignProjectionItem", (ValueProjectionItemV1,), {})
    first = values["public_items"][0]
    foreign = foreign_type(**{item.name: getattr(first, item.name) for item in fields(first)})
    values["public_items"] = (foreign, *values["public_items"][1:])
    with pytest.raises(ValueProjectionEqualityError, match="foreign DTO"):
        ValueProjectionEqualityReceiptV1.build(**values)

    values = _build_values()
    values["expected_plan_sha256"] = True
    with pytest.raises(ValueProjectionEqualityError, match="exact lowercase SHA-256"):
        ValueProjectionEqualityReceiptV1.build(**values)

    values = _build_values()
    values["public_projection"] = values["body_projection"]
    with pytest.raises(ValueProjectionEqualityError, match="aliases"):
        ValueProjectionEqualityReceiptV1.build(**values)


@pytest.mark.parametrize("value", [True, 1.0, "0"])
def test_receipt_exact_integer_replay_rejects_bool_and_foreign_types(value: object) -> None:
    receipt = ValueProjectionEqualityReceiptV1.build(**_build_values())
    row = receipt.to_row()
    row["item_equality_count"] = value
    with pytest.raises(ValueProjectionEqualityError):
        ValueProjectionEqualityReceiptV1.from_row(
            row,
            expected_receipt_sha256=receipt.receipt_sha256,
        )


def test_receipt_subclass_is_rejected() -> None:
    receipt = ValueProjectionEqualityReceiptV1.build(**_build_values())
    foreign = type("ForeignEqualityReceipt", (ValueProjectionEqualityReceiptV1,), {})
    with pytest.raises(ValueProjectionEqualityError, match="foreign exact class"):
        foreign.from_row(
            receipt.to_row(),
            expected_receipt_sha256=receipt.receipt_sha256,
        )


def test_canonical_bytes_reject_duplicate_deep_noncanonical_and_huge_number() -> None:
    receipt = ValueProjectionEqualityReceiptV1.build(**_build_values())
    canonical = receipt.canonical_bytes()
    duplicate = canonical[:-1] + b',"receipt_sha256":"' + b"0" * 64 + b'"}'
    with pytest.raises(ValueProjectionEqualityError, match="duplicate key"):
        ValueProjectionEqualityReceiptV1.from_canonical_bytes(
            duplicate,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
    with pytest.raises(ValueProjectionEqualityError, match="structurally over-bound"):
        ValueProjectionEqualityReceiptV1.from_canonical_bytes(
            b"[" * 20 + b"0" + b"]" * 20,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
    with pytest.raises(ValueProjectionEqualityError, match="not one canonical row"):
        ValueProjectionEqualityReceiptV1.from_canonical_bytes(
            canonical.replace(b":", b": ", 1),
            expected_receipt_sha256=receipt.receipt_sha256,
        )
    huge = canonical.replace(b'"body_input_count":1', b'"body_input_count":' + b"9" * 129)
    with pytest.raises(ValueProjectionEqualityError, match="number is over-bound"):
        ValueProjectionEqualityReceiptV1.from_canonical_bytes(
            huge,
            expected_receipt_sha256=receipt.receipt_sha256,
        )


def test_receipt_reseal_and_external_equality_pin_drift_fail_closed() -> None:
    receipt = ValueProjectionEqualityReceiptV1.build(**_build_values())
    row = receipt.to_row()
    row["plan_sha256"] = _sha("coordinated-plan-drift")
    with pytest.raises(ValueProjectionEqualityError, match="digest differs"):
        ValueProjectionEqualityReceiptV1.from_row(
            row,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
    with pytest.raises(ValueProjectionEqualityError, match="external pin"):
        ValueProjectionEqualityReceiptV1.from_row(
            receipt.to_row(),
            expected_receipt_sha256=_sha("foreign-equality-receipt"),
        )


def test_fully_resealed_denominator_drift_fails_row_and_canonical_replay() -> None:
    receipt = ValueProjectionEqualityReceiptV1.build(**_build_values())
    row = receipt.to_row()
    row["body_input_count"] = 2
    row["public_input_count"] = 2
    _assert_resealed_receipt_rejected(row, match="denominators")

    row = receipt.to_row()
    row["partition_equality_count"] = 1
    _assert_resealed_receipt_rejected(row, match="denominators")


@pytest.mark.parametrize(
    ("count_field", "root_field"),
    [
        ("partition_equality_count", "partition_equality_root_sha256"),
        ("item_equality_count", "item_equality_root_sha256"),
    ],
)
def test_fully_resealed_zero_root_drift_fails_both_directions(
    count_field: str,
    root_field: str,
) -> None:
    receipt = ValueProjectionEqualityReceiptV1.build(**_build_values())
    row = receipt.to_row()
    row[root_field] = _sha(f"foreign-{root_field}")
    _assert_resealed_receipt_rejected(row, match="zero root")

    row = receipt.to_row()
    row[count_field] = 1
    row["body_input_count"] = 2
    row["public_input_count"] = 2
    _assert_resealed_receipt_rejected(row, match="zero root")


def test_fully_resealed_empty_side_root_drift_and_alias_fail_closed() -> None:
    receipt = ValueProjectionEqualityReceiptV1.build(**_build_values())
    row = receipt.to_row()
    row["body_input_root_sha256"] = _sha("foreign-body-side-root")
    _assert_resealed_receipt_rejected(row, match="empty side root")

    row = receipt.to_row()
    row["public_input_root_sha256"] = row["body_input_root_sha256"]
    _assert_resealed_receipt_rejected(row, match="domain-separated")


def test_fully_resealed_bool_and_sha_subclass_fail_exact_replay() -> None:
    receipt = ValueProjectionEqualityReceiptV1.build(**_build_values())
    row = receipt.to_row()
    row["body_input_count"] = True
    row["public_input_count"] = True
    _assert_resealed_receipt_rejected(row, match="exact nonnegative integer")

    foreign_sha = type("ForeignSha", (str,), {})
    row = receipt.to_row()
    row["body_input_root_sha256"] = foreign_sha(row["body_input_root_sha256"])
    resealed = _fully_reseal_receipt_row(row)
    expected = resealed["receipt_sha256"]
    assert type(expected) is str
    with pytest.raises(ValueProjectionEqualityError, match="exact lowercase SHA-256"):
        ValueProjectionEqualityReceiptV1.from_row(
            resealed,
            expected_receipt_sha256=expected,
        )


def test_plan_label_requires_later_operation_cross_binding() -> None:
    first_values = _build_values()
    second_values = _build_values()
    second_values["expected_plan_sha256"] = _sha("independently-relabelled-plan")
    first = ValueProjectionEqualityReceiptV1.build(**first_values)
    second = ValueProjectionEqualityReceiptV1.build(**second_values)

    # This source-independent leaf proves equality of supplied projection evidence;
    # only W2 can replay and bind the actual plan, both side receipts and children,
    # and this complete receipt.  The equality result is plan-independent while the
    # full receipt identity remains bound to the caller-supplied plan label.
    assert first.plan_sha256 != second.plan_sha256
    assert first.equality_root_sha256 == second.equality_root_sha256
    assert first.receipt_sha256 != second.receipt_sha256


def test_source_dependency_boundary_and_one_pass_shape_are_closed() -> None:
    source_path = (
        Path(__file__).parents[3] / "src" / "nbadb" / "contracts" / "value_projection_equality.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    assert imports <= {
        "__future__",
        "dataclasses",
        "hashlib",
        "json",
        "re",
        "typing",
        "nbadb.contracts.value_projection",
    }
    forbidden = (
        "parser",
        "staging",
        "extract",
        "orchestrate",
        "schema",
        "polars",
        "pandera",
        "nba_api",
        "kaggle",
    )
    assert not any(
        name == token or name.startswith(f"{token}.") for name in imports for token in forbidden
    )
    assert source.count("zip(") == 2
    assert "sorted(" not in source
    assert ".index(" not in source
