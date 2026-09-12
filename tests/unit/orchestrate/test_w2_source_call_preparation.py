"""Focused production-evidence preparation tests for one W2 source call."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import duckdb
import pytest

from nbadb.contracts.field_fate_structure import compile_field_fate_structure
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate.body_blob_store import BodyBlobStore
from nbadb.orchestrate.declared_bodyless_packet_store import DeclaredBodylessPacketStore
from nbadb.orchestrate.public_value_authority_store import PublicValueAuthorityStore
from nbadb.orchestrate.raw_request_store import RawRequestAuthorityStore
from nbadb.orchestrate.w2_operation_coordinator import coordinate_w2_source_call
from nbadb.orchestrate.w2_operation_store import W2OperationStore
from nbadb.orchestrate.w2_source_call_preparation import (
    W2SourceCallPreparationError,
    W2SourceCallPreparationRuntime,
    prepare_w2_source_call_candidate,
)
from tests.unit.contracts.test_w2_operation_builder import _valid_values

if TYPE_CHECKING:
    from pathlib import Path


def _binding(values: dict[str, object]) -> LogicalCallReceiptBinding:
    bundle = cast("Any", values["raw_bundle"])
    selected = tuple(item for item in bundle.observations if item.lifecycle == "selected_terminal")
    assert len(selected) == 1
    observation = selected[0]
    route_ids = tuple(
        sorted(
            item.route_id
            for item in bundle.landings
            if item.observation_sha256 == observation.attempt.observation_sha256
        )
    )
    return LogicalCallReceiptBinding(
        logical_call_receipt_sha256=observation.logical_receipt_sha256,
        endpoint_name=route_ids[0].split(":", 1)[0],
        logical_parameters_sha256=observation.attempt.safe_parameters_sha256,
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
        result_route_ids=route_ids,
    )


def _stores(
    root: Path,
    values: dict[str, object],
) -> tuple[BodyBlobStore, DeclaredBodylessPacketStore]:
    bundle = cast("Any", values["raw_bundle"])
    attempt = bundle.observations[0].attempt
    kwargs = {
        "source_sha": attempt.source_sha,
        "run_id": attempt.run_id,
        "run_attempt": attempt.run_attempt,
        "chain_id": attempt.chain_id,
        "lane_id": attempt.lane_id,
    }
    body_root = root / "body"
    bodyless_root = root / "bodyless"
    body_root.mkdir(mode=0o700, exist_ok=True)
    bodyless_root.mkdir(mode=0o700, exist_ok=True)
    body_root.chmod(0o700)
    bodyless_root.chmod(0o700)
    return (
        BodyBlobStore(body_root, **kwargs),
        DeclaredBodylessPacketStore(bodyless_root, **kwargs),
    )


def _prepare(
    connection: duckdb.DuckDBPyConnection,
    root: Path,
    *,
    changes: dict[str, object] | None = None,
):
    values = dict(_valid_values())
    bundle = cast("Any", values["raw_bundle"])
    raw_receipt = RawRequestAuthorityStore(connection).persist_bundle(bundle)
    body_store, bodyless_store = _stores(root, values)
    arguments: dict[str, object] = {
        "logical_call_binding": _binding(values),
        "raw_authority_persistence_receipt": raw_receipt,
        "expected_raw_authority_persistence_receipt_sha256": raw_receipt.receipt_sha256,
        "raw_bundle": bundle,
        "expected_raw_authority_bundle_sha256": bundle.bundle_sha256,
        "committed_staging_readbacks": values["committed_staging_readbacks"],
        "expected_committed_staging_readback_sha256s": values[
            "expected_committed_staging_readback_sha256s"
        ],
        "body_blob_store": body_store,
        "declared_bodyless_packet_store": bodyless_store,
        "recorded_static_attempts": (),
        "field_fate": compile_field_fate_structure(),
        "live_plan_bindings": (),
    }
    if changes:
        arguments.update(changes)
    return prepare_w2_source_call_candidate(**cast("Any", arguments))


def test_prepares_body_readback_routes_and_one_durable_w2_admission(tmp_path: Path) -> None:
    connection = duckdb.connect(":memory:")
    candidate = _prepare(connection, tmp_path)

    admission = coordinate_w2_source_call(
        candidate,
        public_value_store=PublicValueAuthorityStore(connection),
        operation_store=W2OperationStore(connection),
    )

    assert admission.logical_call_receipt_sha256 == (
        candidate.logical_call_binding.logical_call_receipt_sha256
    )
    assert candidate.operation_inputs.body_blob_inventory.descriptor_count == 1
    assert candidate.operation_inputs.body_blob_inventory_readback_receipt.receipt_sha256
    assert candidate.operation_inputs.route_landing_receipts


def test_exact_replay_is_idempotent_for_private_body_objects_and_public_w2_rows(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect(":memory:")
    first = _prepare(connection, tmp_path)
    second = _prepare(connection, tmp_path)

    assert first.operation_inputs == second.operation_inputs
    assert (
        first.raw_authority_persistence_receipt.receipt_sha256
        == second.raw_authority_persistence_receipt.receipt_sha256
    )
    first_admission = coordinate_w2_source_call(
        first,
        public_value_store=PublicValueAuthorityStore(connection),
        operation_store=W2OperationStore(connection),
    )
    second_admission = coordinate_w2_source_call(
        second,
        public_value_store=PublicValueAuthorityStore(connection),
        operation_store=W2OperationStore(connection),
    )
    assert first_admission.admission_sha256 == second_admission.admission_sha256
    assert first_admission.identity_payload() == second_admission.identity_payload()
    assert first_admission.operation == second_admission.operation


@pytest.mark.parametrize(
    "changes,match",
    (
        ({"expected_raw_authority_bundle_sha256": "0" * 64}, "committed W2 source roots"),
        ({"committed_staging_readbacks": []}, "committed staging readbacks"),
        ({"recorded_static_attempts": []}, "recorded static attempts"),
        ({"live_plan_bindings": []}, "live-plan bindings"),
    ),
)
def test_rejects_foreign_shapes_and_changed_external_pins(
    tmp_path: Path,
    changes: dict[str, object],
    match: str,
) -> None:
    connection = duckdb.connect(":memory:")
    with pytest.raises(W2SourceCallPreparationError, match=match):
        _prepare(connection, tmp_path, changes=changes)


def test_rejects_missing_or_extra_live_plan_authority_before_route_projection(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect(":memory:")
    with pytest.raises(W2SourceCallPreparationError, match="live-plan binding"):
        _prepare(connection, tmp_path, changes={"live_plan_bindings": ((object(), "0" * 64),)})


def test_runtime_holds_only_explicit_stores_and_reuses_the_same_pure_boundary(
    tmp_path: Path,
) -> None:
    connection = duckdb.connect(":memory:")
    values = dict(_valid_values())
    bundle = cast("Any", values["raw_bundle"])
    raw_receipt = RawRequestAuthorityStore(connection).persist_bundle(bundle)
    body_store, bodyless_store = _stores(tmp_path, values)
    field_fate = compile_field_fate_structure(upstream_root="")
    runtime = W2SourceCallPreparationRuntime(
        body_blob_store=body_store,
        declared_bodyless_packet_store=bodyless_store,
        field_fate=field_fate,
    )

    candidate = runtime.prepare(
        logical_call_binding=_binding(values),
        raw_authority_persistence_receipt=raw_receipt,
        expected_raw_authority_persistence_receipt_sha256=raw_receipt.receipt_sha256,
        raw_bundle=bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        committed_staging_readbacks=values["committed_staging_readbacks"],
        expected_committed_staging_readback_sha256s=values[
            "expected_committed_staging_readback_sha256s"
        ],
        recorded_static_attempts=(),
    )

    assert candidate.operation_inputs.expected_raw_authority_bundle_sha256 == (bundle.bundle_sha256)


def test_runtime_revalidation_ignores_ambient_upstream_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = dict(_valid_values())
    body_store, bodyless_store = _stores(tmp_path, values)
    field_fate = compile_field_fate_structure(upstream_root="")
    monkeypatch.setenv("NBADB_NBA_API_DOCS_ROOT", str(tmp_path / "ambient-untrusted-root"))

    runtime = W2SourceCallPreparationRuntime(
        body_blob_store=body_store,
        declared_bodyless_packet_store=bodyless_store,
        field_fate=field_fate,
    )

    assert runtime.field_fate is field_fate
