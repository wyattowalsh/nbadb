from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

import nbadb.contracts.independent_live_lossless_table_verifier as verifier_module
import nbadb.contracts.live_lossless_value_authority as authority_module
import nbadb.schemas.raw.nba_api_live_lossless_node as schema_module
from nbadb.contracts.independent_live_lossless_table_verifier import (
    IndependentLiveLosslessTableVerifierError,
    verify_live_lossless_public_table,
)
from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_COLUMNS,
    LIVE_LOSSLESS_REPRESENTATION_KIND,
    LIVE_LOSSLESS_SOURCE_INPUT_KIND,
    LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND,
    MAX_LIVE_LOSSLESS_RECORDS,
    LiveLosslessValueAuthorityV1,
    build_live_lossless_value_authority,
    canonical_json_bytes,
    canonical_sha256,
)
from nbadb.contracts.public_value_types import (
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)
from tests.unit.contracts.test_raw_request_finalization import (
    _case,
    _mixed_live_parent_bundle,
    finalize_raw_request_capture,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from nbadb.contracts.raw_request_authority import RawRequestAuthorityBundleV2


@pytest.fixture(scope="module")
def bundle() -> RawRequestAuthorityBundleV2:
    snapshot, binding, receipts = _case("live")
    return finalize_raw_request_capture(snapshot, binding, receipts)


@pytest.fixture(scope="module")
def authority(bundle: RawRequestAuthorityBundleV2) -> LiveLosslessValueAuthorityV1:
    return build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )


def _verify(authority: LiveLosslessValueAuthorityV1, rows: object | None = None):
    return verify_live_lossless_public_table(
        list(authority.public_rows()) if rows is None else rows,
        expected_raw_authority_bundle_sha256=authority.receipt.raw_authority_bundle_sha256,
        expected_receipt_sha256=authority.receipt.receipt_sha256,
    )


def _reseal_row(
    row: dict[str, object],
    *,
    payload_changes: dict[str, object],
    selector_changes: dict[str, object] | None = None,
) -> dict[str, object]:
    result = dict(row)
    payload = cast("dict[str, object]", json.loads(cast("str", result["payload_json"])))
    digest_name = {
        "result_declaration": "result_set_sha256",
        "result_occurrence": "occurrence_sha256",
        "node": "node_sha256",
        "field_cell": "cell_sha256",
    }[cast("str", result["record_kind"])]
    payload.update(payload_changes)
    payload[digest_name] = canonical_sha256(
        {key: value for key, value in payload.items() if key != digest_name}
    )
    payload_json = canonical_json_bytes(payload, maximum_bytes=64 * 1024 * 1024).decode()
    result["payload_json"] = payload_json
    result["payload_sha256"] = __import__("hashlib").sha256(payload_json.encode()).hexdigest()
    result["source_item_sha256"] = payload[digest_name]
    if selector_changes:
        result.update(selector_changes)
    identity = {
        "schema_version": 1,
        "kind": "raw_nba_api_live_lossless_node_v1",
        **{
            column: result[column]
            for column in LIVE_LOSSLESS_NODE_COLUMNS
            if column not in {"schema_version", "record_sha256"}
        },
    }
    result["record_sha256"] = canonical_sha256(identity)
    return result


def test_public_table_reconstructs_exact_body_only_receipt(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    assert _verify(authority) == authority.receipt


def test_public_table_reconstructs_hybrid_occurrence_and_residual_assignments(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    receipt = _verify(authority)
    residual_rows = tuple(
        row for row in authority.public_rows() if row["ownership_kind"] == "response_residual"
    )

    assert residual_rows
    assert receipt.source_input_kind == LIVE_LOSSLESS_SOURCE_INPUT_KIND
    assert receipt.response_residual_record_count == len(residual_rows)
    assert receipt.response_residual_observation_count == 1
    assert receipt.zero_response_residual_observation_count == 0
    assert receipt.expected_unit_inventory_sha256 == authority.expected_units.inventory_sha256
    assert receipt.expected_unit_root_sha256 == authority.expected_units.unit_root_sha256
    assert authority.expected_units.raw_authority_bundle_sha256 == (
        receipt.raw_authority_bundle_sha256
    )
    assert all(
        row["raw_occurrence_sha256"] is None
        and row["record_kind"] == "node"
        and row["representation_kind"] == LIVE_RESPONSE_RESIDUAL_REPRESENTATION_KIND
        for row in residual_rows
    )
    assert all(
        row["representation_kind"] == LIVE_LOSSLESS_REPRESENTATION_KIND
        for row in authority.public_rows()
        if row["ownership_kind"] == "result_occurrence"
    )


@pytest.mark.parametrize(
    "field",
    ["response_residual_record_count", "response_residual_record_root_sha256"],
)
def test_independently_resealed_residual_partition_is_recomputed_from_rows(
    authority: LiveLosslessValueAuthorityV1,
    field: str,
) -> None:
    first = authority.public_rows()[0]
    forged_value: object = cast("int", first[field]) + 1 if field.endswith("count") else "f" * 64
    rows = [
        _reseal_row(
            row,
            payload_changes={},
            selector_changes={field: forged_value},
        )
        for row in authority.public_rows()
    ]

    with pytest.raises(
        IndependentLiveLosslessTableVerifierError,
        match="residual partition",
    ):
        _verify(authority, rows)


def test_independently_resealed_residual_representation_contradiction_fails(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    index = next(
        index for index, row in enumerate(rows) if row["ownership_kind"] == "response_residual"
    )
    rows[index] = _reseal_row(
        rows[index],
        payload_changes={},
        selector_changes={"representation_kind": LIVE_LOSSLESS_REPRESENTATION_KIND},
    )

    with pytest.raises(
        IndependentLiveLosslessTableVerifierError,
        match="response-residual ownership shape",
    ):
        _verify(authority, rows)


def test_mixed_missing_null_occurrences_reconstruct_without_collapsing_state() -> None:
    bundle, _body = _mixed_live_parent_bundle(("missing", "null"))
    authority = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    receipt = _verify(authority)
    assert receipt == authority.receipt
    assert any(item.presence_kind == "mixed_absent" for item in authority.records)


def test_canonical_zero_live_complement_verifies_from_the_empty_relation() -> None:
    snapshot, binding, receipts = _case("stats")
    bundle = finalize_raw_request_capture(snapshot, binding, receipts)
    authority = build_live_lossless_value_authority(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )

    assert _verify(authority) == authority.receipt
    assert authority.receipt.selected_observation_count == 0
    assert authority.receipt.record_count == 0
    assert authority.receipt.expected_unit_count == 0
    assert authority.receipt.representation_assignment_count == 0
    assert authority.receipt.response_residual_record_count == 0
    assert authority.receipt.response_residual_observation_count == 0
    assert authority.receipt.zero_response_residual_observation_count == 0
    assert authority.expected_units.raw_authority_bundle_sha256 == bundle.bundle_sha256
    assert authority.receipt.expected_unit_inventory_sha256 == (
        authority.expected_units.inventory_sha256
    )


def test_independent_verifier_rejects_foreign_bundle_unit_commitment_reseal(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    original_unit = authority.expected_units.units[0]
    original_assignment = authority.representation_assignments[0]
    forged_unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256="0" * 64,
        unit_ordinal=original_unit.unit_ordinal,
        observation_sha256=original_unit.observation_sha256,
        observation_ordinal=original_unit.observation_ordinal,
        unit_kind=original_unit.unit_kind,
        occurrence_sha256=original_unit.occurrence_sha256,
        occurrence_ordinal=original_unit.occurrence_ordinal,
    )
    forged_assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=forged_unit,
        source_input_kind=original_assignment.source_input_kind,
        representation_kind=original_assignment.representation_kind,
    )
    rows = [
        _reseal_row(
            row,
            payload_changes={},
            selector_changes={
                "expected_unit_sha256": forged_unit.unit_sha256,
                "representation_assignment_sha256": forged_assignment.assignment_sha256,
            },
        )
        if row["expected_unit_sha256"] == original_unit.unit_sha256
        else row
        for row in authority.public_rows()
    ]

    with pytest.raises(
        IndependentLiveLosslessTableVerifierError,
        match="ownership/raw binding",
    ):
        _verify(authority, rows)


@pytest.mark.parametrize("operation", ["missing", "additive", "reordered"])
def test_table_inventory_is_exact_and_ordered(
    authority: LiveLosslessValueAuthorityV1,
    operation: str,
) -> None:
    rows = list(authority.public_rows())
    if operation == "missing":
        rows.pop()
    elif operation == "additive":
        rows.append(dict(rows[-1]))
    else:
        rows[0], rows[1] = rows[1], rows[0]
    with pytest.raises(IndependentLiveLosslessTableVerifierError):
        _verify(authority, rows)


def test_fully_resealed_node_parent_edge_fails_tree_reconstruction(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    index = next(
        index
        for index, row in enumerate(rows)
        if row["record_kind"] == "node" and cast("int", row["node_ordinal"]) > 1
    )
    payload = cast("dict[str, object]", json.loads(cast("str", rows[index]["payload_json"])))
    forged_parent = cast("int", payload["parent_node_ordinal"]) - 1
    rows[index] = _reseal_row(
        rows[index],
        payload_changes={"parent_node_ordinal": forged_parent},
        selector_changes={"parent_node_ordinal": forged_parent},
    )
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="parent path/depth"):
        _verify(authority, rows)


def test_fully_resealed_result_denominator_fails_occurrence_algebra(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    index = next(
        index for index, row in enumerate(rows) if row["record_kind"] == "result_declaration"
    )
    payload = cast("dict[str, object]", json.loads(cast("str", rows[index]["payload_json"])))
    rows[index] = _reseal_row(
        rows[index],
        payload_changes={
            "result_occurrence_count": cast("int", payload["result_occurrence_count"]) + 1
        },
    )
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="denominators"):
        _verify(authority, rows)


def test_fully_resealed_occurrence_ordinal_fails_per_result_order(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    index = next(
        index for index, row in enumerate(rows) if row["record_kind"] == "result_occurrence"
    )
    rows[index] = _reseal_row(
        rows[index],
        payload_changes={"occurrence_ordinal": 9},
        selector_changes={"result_set_occurrence": 9},
    )
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="declaration/raw binding"):
        _verify(authority, rows)


def test_fully_resealed_occurrence_cardinality_fails_reconstructed_container(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    index = next(
        index
        for index, row in enumerate(rows)
        if row["record_kind"] == "result_occurrence"
        and cast("str", row["result_set_name"]) == "scoreboard_games"
    )
    payload = cast("dict[str, object]", json.loads(cast("str", rows[index]["payload_json"])))
    rows[index] = _reseal_row(
        rows[index],
        payload_changes={"row_count": cast("int", payload["row_count"]) + 1},
    )
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="exact node"):
        _verify(authority, rows)


def test_fully_resealed_header_permutation_fails_field_cell_binding(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    index = next(
        index
        for index, row in enumerate(rows)
        if row["record_kind"] == "result_declaration"
        and row["result_set_name"] == "scoreboard_games"
    )
    payload = cast("dict[str, object]", json.loads(cast("str", rows[index]["payload_json"])))
    headers = list(cast("list[str]", payload["ordered_headers"]))
    headers[0], headers[1] = headers[1], headers[0]
    rows[index] = _reseal_row(
        rows[index],
        payload_changes={
            "ordered_headers": headers,
            "headers_sha256": canonical_sha256(headers),
        },
    )
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="node/declaration"):
        _verify(authority, rows)


def test_fully_resealed_node_depth_fails_tree_reconstruction(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    index = next(
        index
        for index, row in enumerate(rows)
        if row["record_kind"] == "node" and cast("int", row["node_ordinal"]) > 0
    )
    payload = cast("dict[str, object]", json.loads(cast("str", rows[index]["payload_json"])))
    rows[index] = _reseal_row(
        rows[index],
        payload_changes={"depth": cast("int", payload["depth"]) + 1},
    )
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="parent path/depth"):
        _verify(authority, rows)


def test_fully_resealed_presence_container_mismatch_fails_before_receipt_check(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    index = next(
        index
        for index, row in enumerate(rows)
        if row["record_kind"] == "result_occurrence"
        and row["result_set_name"] == "scoreboard_games"
    )
    rows[index] = _reseal_row(
        rows[index],
        payload_changes={
            "container_kind": "nba_api_live_json_object",
            "presence_kind": "empty_array",
            "row_count": 0,
        },
    )
    with pytest.raises(
        IndependentLiveLosslessTableVerifierError,
        match="empty-array occurrence algebra",
    ):
        _verify(authority, rows)


def test_fully_resealed_field_ordinal_fails_header_binding(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    index = next(index for index, row in enumerate(rows) if row["record_kind"] == "field_cell")
    payload = cast("dict[str, object]", json.loads(cast("str", rows[index]["payload_json"])))
    forged = cast("int", payload["field_ordinal"]) + 50
    rows[index] = _reseal_row(
        rows[index],
        payload_changes={"field_ordinal": forged},
        selector_changes={"field_ordinal": forged},
    )
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="node/declaration"):
        _verify(authority, rows)


def test_relabelled_raw_occurrence_binding_fails_result_partition_join(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = list(authority.public_rows())
    declarations = [row for row in rows if row["record_kind"] == "result_declaration"]
    first = declarations[0]
    second = declarations[1]
    target = rows.index(first)
    changed = dict(first)
    changed["raw_occurrence_sha256"] = second["raw_occurrence_sha256"]
    identity = {
        "schema_version": 1,
        "kind": "raw_nba_api_live_lossless_node_v1",
        **{
            column: changed[column]
            for column in LIVE_LOSSLESS_NODE_COLUMNS
            if column not in {"schema_version", "record_sha256"}
        },
    }
    changed["record_sha256"] = canonical_sha256(identity)
    rows[target] = changed
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="raw binding"):
        _verify(authority, rows)


def test_fully_resealed_decoder_anomaly_inventory_is_independently_recomputed(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    anomaly_json = '["additive_field"]'
    anomaly_sha = hashlib.sha256(anomaly_json.encode("utf-8")).hexdigest()
    rows = [
        _reseal_row(
            row,
            payload_changes={},
            selector_changes={
                "decoder_anomaly_codes_json": anomaly_json,
                "decoder_anomaly_codes_sha256": anomaly_sha,
            },
        )
        for row in authority.public_rows()
    ]
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="anomaly inventory"):
        _verify(authority, rows)


def test_fully_resealed_multi_observation_rows_must_follow_public_attempt_order(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows: list[dict[str, object]] = []
    source_rows = authority.public_rows()
    for observation_ordinal, logical_invocation_sha256 in (
        (0, "f" * 64),
        (1, "0" * 64),
    ):
        for observation_record_ordinal, row in enumerate(source_rows):
            rows.append(
                _reseal_row(
                    row,
                    payload_changes={},
                    selector_changes={
                        "logical_invocation_sha256": logical_invocation_sha256,
                        "observation_ordinal": observation_ordinal,
                        "global_record_ordinal": len(rows),
                        "observation_record_ordinal": observation_record_ordinal,
                    },
                )
            )
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="attempt order"):
        _verify(authority, rows)


def test_coordinated_foreign_bundle_and_receipt_reseal_cannot_cross_external_pins(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = [dict(row) for row in authority.public_rows()]
    for index, row in enumerate(rows):
        row["raw_authority_bundle_sha256"] = "0" * 64
        identity = {
            "schema_version": 1,
            "kind": "raw_nba_api_live_lossless_node_v1",
            **{
                column: row[column]
                for column in LIVE_LOSSLESS_NODE_COLUMNS
                if column not in {"schema_version", "record_sha256"}
            },
        }
        row["record_sha256"] = canonical_sha256(identity)
        rows[index] = row
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="externally pinned"):
        _verify(authority, rows)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: {**row, "schema_version": True},
        lambda row: {**row, "parser_input_length": True},
        lambda row: {**row, "payload_json": '{"a":1,"a":2}'},
        lambda row: {**row, "payload_json": '{"value":NaN}'},
    ],
)
def test_hostile_types_duplicate_keys_and_nonfinite_json_fail_closed(
    authority: LiveLosslessValueAuthorityV1,
    mutation: Callable[[dict[str, object]], dict[str, object]],
) -> None:
    rows = list(authority.public_rows())
    rows[0] = mutation(rows[0])
    with pytest.raises(IndependentLiveLosslessTableVerifierError):
        _verify(authority, rows)


def test_foreign_equality_and_tuple_subclasses_never_authorize_rows(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    class AlwaysEqual(str):
        def __eq__(self, _other: object) -> bool:
            return True

        def __hash__(self) -> int:
            return hash(str(self))

    class ForeignRows(tuple[dict[str, object], ...]):
        pass

    rows = list(authority.public_rows())
    rows[0]["record_sha256"] = AlwaysEqual(cast("str", rows[0]["record_sha256"]))
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="exact lowercase"):
        _verify(authority, rows)
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="exact list or tuple"):
        _verify(authority, ForeignRows(authority.public_rows()))


def test_resource_preflight_rejects_foreign_sequence_before_iteration(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    class BombList(list[dict[str, object]]):
        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("must not iterate")

    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="exact list or tuple"):
        _verify(authority, BombList(authority.public_rows()))
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="count"):
        verify_live_lossless_public_table(
            [],
            expected_raw_authority_bundle_sha256=authority.receipt.raw_authority_bundle_sha256,
            expected_receipt_sha256=authority.receipt.receipt_sha256,
        )
    assert authority.receipt.record_count < MAX_LIVE_LOSSLESS_RECORDS


def test_cumulative_utf8_bound_counts_outer_canonical_json(
    authority: LiveLosslessValueAuthorityV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = list(authority.public_rows())
    total_without_outer_canonical = sum(
        len(cast("str", value).encode("utf-8"))
        for row in rows
        for column, value in row.items()
        if column in verifier_module.LIVE_LOSSLESS_TEXT_COLUMNS
        and column != "canonical_json"
        and value is not None
    )
    outer_canonical_bytes = sum(
        len(cast("str", row["canonical_json"]).encode("utf-8"))
        for row in rows
        if row["canonical_json"] is not None
    )
    assert outer_canonical_bytes > 0
    monkeypatch.setattr(
        verifier_module,
        "MAX_LIVE_LOSSLESS_TOTAL_CANONICAL_BYTES",
        total_without_outer_canonical,
    )
    with pytest.raises(IndependentLiveLosslessTableVerifierError, match="cumulative"):
        _verify(authority, rows)


def test_public_verifier_import_boundary_has_no_parser_body_or_staging_dependencies() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "src"
        / "nbadb"
        / "contracts"
        / "independent_live_lossless_table_verifier.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        name
        for name in imported
        if name.startswith("nbadb.extract")
        or name.startswith("nbadb.orchestrate")
        or "independent_live_value_decoder" in name
        or "staging" in name
        or "parser" in name
    }
    assert forbidden == set()
    assert imported <= {
        "__future__",
        "collections",
        "collections.abc",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
        "math",
        "re",
        "typing",
        "nbadb.contracts.live_lossless_value_authority",
        "nbadb.contracts.public_value_types",
    }


def test_verifier_errors_do_not_echo_secret_shaped_values(
    authority: LiveLosslessValueAuthorityV1,
) -> None:
    rows = copy.deepcopy(list(authority.public_rows()))
    sentinel = "ghp_123456789012345678901234567890"
    rows[0]["payload_json"] = json.dumps({"apiKey": sentinel}, separators=(",", ":"))
    with pytest.raises(IndependentLiveLosslessTableVerifierError) as captured:
        _verify(authority, rows)
    assert sentinel not in str(captured.value)


@pytest.mark.parametrize(
    "secret_payload",
    [
        {"Authorization": "Bearer ABCDEFGHIJKLMNOPQRST"},
        {"value": "Bearer ABCDEFGHIJKLMNOPQRST"},
        {"value": "Basic QUJDREVGR0hJSktM"},
        {"value": "prefix Authorization: Bearer ABCDEFGHIJKLMNOPQRST suffix"},
        {"value": "prefix Authorization: Basic QUJDREVGR0hJSktM suffix"},
        {"value": "prefix Bearer ABCDEFGHIJKLMNOPQRST suffix"},
        {"value": "prefix Basic QUJDREVGR0hJSktM suffix"},
        {"value": "/Users/private-name"},
        {"value": "/home/private-name"},
        {"value": "/private/var"},
        {"value": "prefix /Users/private-name suffix"},
        {"value": "prefix /home/private-name suffix"},
        {"value": "prefix /private/var suffix"},
        {"value": "/Users/private-name:"},
        {"value": "/home/private-name,"},
        {"value": "/private/var."},
        {"value": "eyJabcdefgh.abcdefgh.abcdefgh"},
        {"nested": {"authToken": "opaque-value"}},
        {"nested": {"sessionKey": "opaque-value"}},
        {"session": "opaque-value"},
    ],
)
def test_verifier_rejects_auth_session_and_token_shapes_without_echo(
    authority: LiveLosslessValueAuthorityV1,
    secret_payload: dict[str, object],
) -> None:
    rows = copy.deepcopy(list(authority.public_rows()))
    rows[0]["payload_json"] = json.dumps(
        secret_payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    with pytest.raises(IndependentLiveLosslessTableVerifierError) as captured:
        _verify(authority, rows)
    assert "opaque-value" not in str(captured.value)
    assert "ABCDEFGHIJKLMNOPQRST" not in str(captured.value)


def test_secret_predicate_patterns_flags_and_behavior_remain_independent_but_equal() -> None:
    names = (
        "_AUTHORIZATION_HEADER_SECRET_RE",
        "_BEARER_SECRET_RE",
        "_BASIC_SECRET_RE",
        "_LOCAL_PATH_VALUE_RE",
    )
    modules = (authority_module, schema_module, verifier_module)
    for name in names:
        patterns = tuple(getattr(module, name) for module in modules)
        assert len({(pattern.pattern, pattern.flags) for pattern in patterns}) == 1

    hostile = (
        "prefix Authorization: Bearer ABCDEFGHIJKLMNOPQRST suffix",
        "prefix Authorization: Basic QUJDREVGR0hJSktM suffix",
        "prefix Bearer ABCDEFGHIJKLMNOPQRST suffix",
        "prefix Basic QUJDREVGR0hJSktM suffix",
        "/Users/private-name",
        "/home/private-name",
        "/private/var",
        "prefix /Users/private-name suffix",
        "prefix /home/private-name suffix",
        "prefix /private/var suffix",
        "/Users/private-name:",
        "/home/private-name,",
        "/private/var.",
    )
    for value in hostile:
        with pytest.raises(authority_module.LiveLosslessValueAuthorityError):
            authority_module._reject_public_text(value)
        assert schema_module._safe_text(value) is False
        with pytest.raises(IndependentLiveLosslessTableVerifierError):
            verifier_module._reject_text(value)

    for value in (
        "Authorization is required for League Pass",
        "Bearer of the scoring load",
        "Basic Basketball",
    ):
        authority_module._reject_public_text(value)
        assert schema_module._safe_text(value) is True
        verifier_module._reject_text(value)


@pytest.mark.parametrize(
    ("column", "invalid"),
    [
        ("live_snapshot_at", "2026-08-27T12:00:00+00:00"),
        ("chain_id", "chain/with/slash"),
    ],
)
def test_verifier_timestamp_and_id_policy_matches_authority_and_schema(
    authority: LiveLosslessValueAuthorityV1,
    column: str,
    invalid: str,
) -> None:
    rows = list(authority.public_rows())
    rows[0][column] = invalid
    with pytest.raises(IndependentLiveLosslessTableVerifierError):
        _verify(authority, rows)
