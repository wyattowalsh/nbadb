from __future__ import annotations

import hashlib
import inspect

import duckdb
import pytest

from nbadb.contracts import transform_output_operation_data_authority as authority
from nbadb.contracts import transform_output_operation_raw_snapshot_verifier as verifier


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _source(seed: str) -> str:
    return hashlib.sha1(seed.encode(), usedforsecurity=False).hexdigest()


def _context() -> authority._OperationContextV1:
    return authority._OperationContextV1(
        operation_sha256=_sha("operation"),
        source_sha=_source("source"),
        chain_id="chain-current",
        transaction_generation=3,
        transaction_generation_identity_sha256=_sha("generation"),
        duckdb_snapshot_sha256=_sha("snapshot"),
    )


def _locator(context: authority._OperationContextV1, label: str):
    return authority.DurableRawTerminalManifestLocatorV1._seal(
        source_sha=context.source_sha,
        run_id=7,
        run_attempt=1,
        chain_id=context.chain_id,
        lane_id=f"lane-{label}",
        scope_sha256=_sha(f"scope:{label}"),
        route_authority_sha256=_sha(f"route-authority:{label}"),
        request_closure_authority_sha256=_sha(f"closure:{label}"),
        field_authority_sha256=_sha(f"field:{label}"),
        model_authority_sha256=_sha(f"model:{label}"),
        authority_set_sha256=_sha(f"set:{label}"),
        expected_call_count=1,
        expected_call_inventory_sha256=_sha(f"calls:{label}"),
        route_count=1,
        route_inventory_sha256=_sha(f"routes:{label}"),
        terminal_generation=0,
        terminal_parent_manifest_sha256=None,
        terminal_manifest_sha256=_sha(f"manifest:{label}"),
        terminal_operation_sha256=_sha(f"operation:{label}"),
        terminal_receipt_count=1,
        terminal_receipt_inventory_sha256=_sha(f"receipts:{label}"),
        terminal_manifest_canonical_byte_length=100,
        terminal_manifest_canonical_sha256=_sha(f"bytes:{label}"),
    )


def _denominator():
    context = _context()
    lane = _sha("lane")
    executable = authority.FullExtractionExecutableRawMemberV1._seal(
        normalized_lane_sha256=lane,
        terminal_locator=_locator(context, "lane"),
    )
    return authority.FullExtractionRawOperationDenominatorV1._seal(
        operation_context=context,
        normalized_manifest_lane_sha256s=(lane,),
        executable_members=(executable,),
        blocked_members=(),
        discovery_member=authority.RawAuxiliaryTerminalMemberV1._seal(
            auxiliary_role="discovery_seed", terminal_locator=_locator(context, "discovery")
        ),
        live_member=authority.RawAuxiliaryTerminalMemberV1._seal(
            auxiliary_role="live_snapshot", terminal_locator=_locator(context, "live")
        ),
    )


def _successor_denominator():
    context = _context()
    calls = (_sha("successor-call"),)
    routes = (_sha("successor-route"),)
    locator = authority.DurableRawTerminalManifestLocatorV1._seal(
        source_sha=context.source_sha,
        run_id=9,
        run_attempt=1,
        chain_id=context.chain_id,
        lane_id="lane-successor",
        scope_sha256=_sha("successor-scope"),
        route_authority_sha256=_sha("successor-route-authority"),
        request_closure_authority_sha256=_sha("successor-closure"),
        field_authority_sha256=_sha("successor-field"),
        model_authority_sha256=_sha("successor-model"),
        authority_set_sha256=_sha("successor-set"),
        expected_call_count=1,
        expected_call_inventory_sha256=authority._inventory_root(
            "nbadb_successor_dispatch_call_inventory_v1", calls
        ),
        route_count=1,
        route_inventory_sha256=authority._inventory_root(
            "nbadb_successor_requested_route_inventory_v1", routes
        ),
        terminal_generation=0,
        terminal_parent_manifest_sha256=None,
        terminal_manifest_sha256=_sha("successor-manifest"),
        terminal_operation_sha256=_sha("successor-operation"),
        terminal_receipt_count=1,
        terminal_receipt_inventory_sha256=_sha("successor-receipts"),
        terminal_manifest_canonical_byte_length=100,
        terminal_manifest_canonical_sha256=_sha("successor-bytes"),
    )
    return authority.SuccessorRawOperationDenominatorV1._seal(
        operation_context=context,
        prior_operation_data_evidence_sha256=_sha("prior-evidence"),
        prior_raw_snapshot_sha256=_sha("prior-snapshot"),
        prior_raw_terminal_member_count=3,
        prior_raw_terminal_inventory_sha256=_sha("prior-inventory"),
        successor_execution_plan_sha256=_sha("successor-execution-plan"),
        planning_generation_manifest_sha256=_sha("planning-generation-manifest"),
        planned_route_replacement_bindings_sha256=_sha("route-replacement-bindings"),
        dispatch_call_count=len(calls),
        dispatch_call_inventory_sha256=locator.expected_call_inventory_sha256,
        requested_route_binding_count=len(routes),
        requested_route_binding_inventory_sha256=locator.route_inventory_sha256,
        delta_terminal_locator=locator,
    )


def _compile(denominator, connection):
    context = denominator.operation_context
    return verifier.compile_verified_operation_raw_snapshot(
        denominator,
        operation_sha256=context.operation_sha256,
        source_sha=context.source_sha,
        chain_id=context.chain_id,
        transaction_generation=context.transaction_generation,
        transaction_generation_identity_sha256=(context.transaction_generation_identity_sha256),
        duckdb_snapshot_sha256=context.duckdb_snapshot_sha256,
        connection=connection,
    )


def test_exact_join_seals_full_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    denominator = _denominator()
    expected = tuple(
        sorted(
            (
                denominator.executable_members[0].terminal_locator,
                denominator.discovery_member.terminal_locator,
                denominator.live_member.terminal_locator,
            ),
            key=lambda item: item.locator_sha256,
        )
    )
    monkeypatch.setattr(verifier, "_require_exact_relations", lambda *_: None)
    monkeypatch.setattr(verifier, "_load_locators", lambda *_: expected)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("BEGIN")
        snapshot = _compile(denominator, connection)
    finally:
        connection.close()
    assert snapshot.operation_kind == "full_extraction"
    assert snapshot.denominator == denominator


def test_exact_join_seals_successor_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    denominator = _successor_denominator()
    monkeypatch.setattr(verifier, "_require_exact_relations", lambda *_: None)
    monkeypatch.setattr(
        verifier, "_load_locators", lambda *_: (denominator.delta_terminal_locator,)
    )
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("BEGIN")
        snapshot = _compile(denominator, connection)
    finally:
        connection.close()
    assert snapshot.operation_kind == "successor"
    assert snapshot.denominator == denominator


def test_missing_extra_duplicate_and_foreign_locators_fail(monkeypatch) -> None:
    denominator = _denominator()
    expected = (
        denominator.executable_members[0].terminal_locator,
        denominator.discovery_member.terminal_locator,
        denominator.live_member.terminal_locator,
    )
    monkeypatch.setattr(verifier, "_require_exact_relations", lambda *_: None)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("BEGIN")
        for observed in (expected[:-1], (*expected, expected[-1]), (expected[0],)):
            monkeypatch.setattr(verifier, "_load_locators", lambda *_, rows=observed: rows)
            with pytest.raises(verifier.OperationRawSnapshotVerificationError, match="exact-join"):
                _compile(denominator, connection)
    finally:
        connection.close()


@pytest.mark.parametrize(
    "field",
    (
        "operation_sha256",
        "source_sha",
        "chain_id",
        "transaction_generation",
        "transaction_generation_identity_sha256",
        "duckdb_snapshot_sha256",
    ),
)
def test_explicit_snapshot_context_is_mandatory(field: str) -> None:
    denominator = _denominator()
    context = denominator.operation_context
    values = {
        "operation_sha256": context.operation_sha256,
        "source_sha": context.source_sha,
        "chain_id": context.chain_id,
        "transaction_generation": context.transaction_generation,
        "transaction_generation_identity_sha256": context.transaction_generation_identity_sha256,
        "duckdb_snapshot_sha256": context.duckdb_snapshot_sha256,
    }
    values[field] = 99 if field == "transaction_generation" else _sha(f"foreign:{field}")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("BEGIN")
        with pytest.raises(verifier.OperationRawSnapshotVerificationError, match="context"):
            verifier.compile_verified_operation_raw_snapshot(
                denominator, connection=connection, **values
            )
    finally:
        connection.close()


def test_public_api_has_no_maps_presence_flags_or_physical_names() -> None:
    parameters = inspect.signature(verifier.compile_verified_operation_raw_snapshot).parameters
    assert tuple(parameters) == (
        "denominator",
        "operation_sha256",
        "source_sha",
        "chain_id",
        "transaction_generation",
        "transaction_generation_identity_sha256",
        "duckdb_snapshot_sha256",
        "connection",
    )
    assert not ({"map", "present", "physical", "terminal"} & set(parameters))


def test_verifier_does_not_issue_transaction_control_or_create_relations() -> None:
    source = inspect.getsource(verifier)
    for forbidden in ("BEGIN", "COMMIT", "ROLLBACK", "CREATE TEMP", ".register("):
        assert forbidden not in source


def test_verifier_rejects_autocommit_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    denominator = _denominator()
    monkeypatch.setattr(verifier, "_require_exact_relations", lambda *_: None)
    monkeypatch.setattr(verifier, "_load_locators", lambda *_: ())
    connection = duckdb.connect(":memory:")
    try:
        with pytest.raises(
            verifier.OperationRawSnapshotVerificationError,
            match="caller-owned DuckDB transaction",
        ):
            _compile(denominator, connection)
    finally:
        connection.close()
