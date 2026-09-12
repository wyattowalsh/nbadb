"""Focused adversarial tests for the pure exact-six W2 publication verifier."""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

import nbadb.contracts.w2_publication_verifier as module
from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
)
from nbadb.contracts.public_table_value_projection import (
    RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
    RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
    RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
)
from nbadb.contracts.stats_lossless_value_authority import STATS_LOSSLESS_RECORD_SCHEMA_SHA256
from nbadb.contracts.w2_operation_builder import build_w2_operation
from nbadb.contracts.w2_publication_verifier import (
    W2PublicationVerificationReceiptV1,
    W2PublicationVerifierError,
    verify_w2_publication,
)
from nbadb.schemas.raw.nba_api_w2_operation import (
    RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
)
from tests.unit.contracts.test_public_value_authority_adapter import _live_bundle
from tests.unit.contracts.test_raw_request_authority import _stats_fallback_bundle
from tests.unit.contracts.test_raw_result_cell_authority import _stats_case
from tests.unit.contracts.test_w2_operation_builder import (
    _build_with_unrelated_staging_bypassed,
    _source_values,
    _valid_values,
)

if TYPE_CHECKING:
    from nbadb.contracts.w2_operation import W2OperationReceiptV1


def _arguments(
    values: dict[str, object],
    operation: W2OperationReceiptV1,
) -> dict[str, object]:
    bundle = cast("Any", values["raw_bundle"])
    return {
        "raw_authority_bundle": bundle,
        "expected_raw_authority_bundle_sha256": bundle.bundle_sha256,
        "result_cell_rows": values["result_cell_rows"],
        "expected_result_cell_schema_sha256": RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
        "stats_lossless_rows": values["stats_lossless_rows"],
        "expected_stats_lossless_schema_sha256": STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
        "live_lossless_rows": values["live_lossless_rows"],
        "expected_live_lossless_schema_sha256": LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        "value_representation_rows": values["value_representation_rows"],
        "expected_value_representation_schema_sha256": (
            RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256
        ),
        "route_field_landing_rows": values["route_field_landing_rows"],
        "expected_route_field_landing_schema_sha256": (
            RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256
        ),
        "w2_operation_rows": (operation.to_row(),),
        "expected_w2_operation_schema_sha256": RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
        "expected_operation_key_sha256": operation.operation_key_sha256,
        "expected_operation_receipt_sha256": operation.operation_receipt_sha256,
    }


@cache
def _empty_case() -> tuple[dict[str, object], W2OperationReceiptV1]:
    values = dict(_valid_values())
    return values, build_w2_operation(**values)


def _verify(
    values: dict[str, object],
    operation: W2OperationReceiptV1,
    **changes: object,
) -> W2PublicationVerificationReceiptV1:
    arguments = _arguments(values, operation)
    arguments.update(changes)
    return verify_w2_publication(**arguments)


def test_verifies_empty_value_relations_and_replays_bounded_receipt() -> None:
    values, operation = _empty_case()

    first = _verify(values, operation)
    second = _verify(values, operation)

    assert type(first) is W2PublicationVerificationReceiptV1
    assert first == second
    assert first.operation_key_sha256 == operation.operation_key_sha256
    assert first.operation_receipt_sha256 == operation.operation_receipt_sha256
    assert first.result_cell_row_count == 0
    assert first.stats_lossless_row_count == 0
    assert first.live_lossless_row_count == 0
    assert first.value_representation_row_count == 1
    assert first.route_field_landing_row_count == 1
    assert first.relation_row_count == 2
    assert first.publication_row_count == 3
    assert W2PublicationVerificationReceiptV1.from_row(first.to_row()) == first
    assert len(first.canonical_bytes()) < 8_192


@pytest.mark.parametrize(
    ("pin_name", "expected_message"),
    [
        (
            "expected_result_cell_schema_sha256",
            "exact-six schema authority",
        ),
        (
            "expected_stats_lossless_schema_sha256",
            "exact-six schema authority",
        ),
        (
            "expected_live_lossless_schema_sha256",
            "exact-six schema authority",
        ),
        (
            "expected_value_representation_schema_sha256",
            "exact-six schema authority",
        ),
        (
            "expected_route_field_landing_schema_sha256",
            "exact-six schema authority",
        ),
        (
            "expected_w2_operation_schema_sha256",
            "exact-six schema authority",
        ),
    ],
)
def test_pins_all_six_schema_authorities_before_bundle_traversal(
    pin_name: str,
    expected_message: str,
) -> None:
    values, operation = _empty_case()

    with pytest.raises(W2PublicationVerifierError, match=expected_message):
        _verify(
            values,
            operation,
            raw_authority_bundle=object(),
            **{pin_name: "0" * 64},
        )


def test_requires_exact_tuple_and_exact_ordered_row_columns() -> None:
    values, operation = _empty_case()
    assignment_rows = cast(
        "tuple[dict[str, object], ...]",
        values["value_representation_rows"],
    )
    reordered = dict(reversed(tuple(assignment_rows[0].items())))

    with pytest.raises(W2PublicationVerifierError, match="bounded exact tuple"):
        _verify(values, operation, value_representation_rows=list(assignment_rows))
    with pytest.raises(W2PublicationVerifierError, match="exact ordered columns"):
        _verify(values, operation, value_representation_rows=(reordered,))


def test_rejects_missing_duplicate_and_reordered_target_relations() -> None:
    values, operation = _empty_case()
    assignment_rows = cast(
        "tuple[dict[str, object], ...]",
        values["value_representation_rows"],
    )
    route_rows = cast(
        "tuple[dict[str, object], ...]",
        values["route_field_landing_rows"],
    )

    with pytest.raises(W2PublicationVerifierError):
        _verify(values, operation, value_representation_rows=())
    with pytest.raises(W2PublicationVerifierError):
        _verify(values, operation, value_representation_rows=assignment_rows * 2)
    with pytest.raises(W2PublicationVerifierError):
        _verify(values, operation, route_field_landing_rows=route_rows * 2)
    with pytest.raises(W2PublicationVerifierError, match="exactly one"):
        _verify(values, operation, w2_operation_rows=())
    with pytest.raises(W2PublicationVerifierError, match="exactly one"):
        _verify(values, operation, w2_operation_rows=(operation.to_row(),) * 2)


def test_rejects_hostile_unicode_and_large_number_without_echo() -> None:
    values, operation = _empty_case()
    rows = cast("tuple[dict[str, object], ...]", values["value_representation_rows"])
    unicode_row = dict(rows[0])
    unicode_row["source_input_kind"] = "private-\ud800-token"
    number_row = dict(rows[0])
    number_row["unit_ordinal"] = 1 << 200

    for candidate, secret in (
        (unicode_row, "private"),
        (number_row, str(1 << 200)),
    ):
        with pytest.raises(W2PublicationVerifierError) as captured:
            _verify(values, operation, value_representation_rows=(candidate,))
        assert secret not in str(captured.value)
        assert captured.value.__cause__ is None


def test_sanitizes_hostile_child_error_even_when_it_uses_public_error_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values, operation = _empty_case()
    secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"

    def hostile(_cls: object, _row: object) -> object:
        raise W2PublicationVerifierError(secret)

    monkeypatch.setattr(
        module.ValueRepresentationAssignmentV1,
        "from_row",
        classmethod(hostile),
    )
    with pytest.raises(
        W2PublicationVerifierError,
        match="sanitized dependency replay",
    ) as captured:
        _verify(values, operation)
    assert secret not in str(captured.value)
    assert captured.value.__cause__ is None


def test_rejects_over_bound_inputs_before_child_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values, operation = _empty_case()
    monkeypatch.setattr(module, "MAX_W2_PUBLICATION_INPUT_ROWS", 0)

    with pytest.raises(W2PublicationVerifierError, match="bounded exact tuple"):
        _verify(values, operation)


def test_rectangular_result_ownership_comes_from_selected_raw_occurrences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, expected_cells = _stats_case()
    values = _source_values(bundle)
    operation = _build_with_unrelated_staging_bypassed(monkeypatch, values)

    receipt = _verify(values, operation)
    assert receipt.result_cell_row_count == len(expected_cells) > 1

    rows = cast("tuple[dict[str, object], ...]", values["result_cell_rows"])
    with pytest.raises(W2PublicationVerifierError):
        _verify(values, operation, result_cell_rows=(rows[1], rows[0], *rows[2:]))
    with pytest.raises(W2PublicationVerifierError):
        _verify(values, operation, result_cell_rows=rows[:-1])
    with pytest.raises(W2PublicationVerifierError):
        _verify(values, operation, result_cell_rows=(*rows, rows[0]))


def test_stats_lossless_rows_require_canonical_bundle_local_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, *_rest = _stats_fallback_bundle("missing_result")
    values = _source_values(bundle)
    operation = _build_with_unrelated_staging_bypassed(monkeypatch, values)
    rows = cast("tuple[dict[str, object], ...]", values["stats_lossless_rows"])

    receipt = _verify(values, operation)
    assert receipt.stats_lossless_row_count == len(rows) > 1
    with pytest.raises(W2PublicationVerifierError):
        _verify(values, operation, stats_lossless_rows=(rows[1], rows[0], *rows[2:]))


def test_live_lossless_rows_require_global_and_observation_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _source_values(_live_bundle())
    operation = _build_with_unrelated_staging_bypassed(monkeypatch, values)
    rows = cast("tuple[dict[str, object], ...]", values["live_lossless_rows"])

    receipt = _verify(values, operation)
    assert receipt.live_lossless_row_count == len(rows) > 1
    with pytest.raises(W2PublicationVerifierError):
        _verify(values, operation, live_lossless_rows=(rows[1], rows[0], *rows[2:]))


def test_filters_complete_unrelated_bundle_rows_without_changing_target_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_values, target_operation = _empty_case()
    foreign_bundle, *_rest = _stats_fallback_bundle("header_drift")
    foreign_values = _source_values(foreign_bundle)
    foreign_operation = _build_with_unrelated_staging_bypassed(
        monkeypatch,
        foreign_values,
    )
    changes: dict[str, object] = {}
    for name in (
        "result_cell_rows",
        "stats_lossless_rows",
        "live_lossless_rows",
        "value_representation_rows",
        "route_field_landing_rows",
    ):
        target_rows = cast("tuple[object, ...]", target_values[name])
        foreign_rows = cast("tuple[object, ...]", foreign_values[name])
        changes[name] = (*target_rows, *foreign_rows)
    changes["w2_operation_rows"] = (
        target_operation.to_row(),
        foreign_operation.to_row(),
    )

    baseline = _verify(target_values, target_operation)
    mixed = _verify(target_values, target_operation, **changes)

    assert mixed == baseline


def test_result_replay_work_is_bounded_by_a_constant_per_input_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _expected_cells = _stats_case()
    values = _source_values(bundle)
    operation = _build_with_unrelated_staging_bypassed(monkeypatch, values)
    rows = cast("tuple[dict[str, object], ...]", values["result_cell_rows"])
    original = module.RawNbaApiResultCellV2.from_row
    calls = 0

    def counted(_cls: object, row: object) -> object:
        nonlocal calls
        calls += 1
        return original(row)

    monkeypatch.setattr(
        module.RawNbaApiResultCellV2,
        "from_row",
        classmethod(counted),
    )

    receipt = _verify(values, operation)

    assert receipt.result_cell_row_count == len(rows)
    assert len(rows) <= calls <= len(rows) * 3


def test_source_has_no_forbidden_runtime_or_persistence_imports() -> None:
    source_path = Path(module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    forbidden = (
        "nbadb.extract",
        "nbadb.load",
        "nbadb.orchestrate",
        "nbadb.kaggle",
        "staging_batches",
        "stats_response_parser",
    )
    assert not any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in imports
        for prefix in forbidden
    )
