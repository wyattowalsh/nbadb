"""Focused runtime tests for exact per-source-call W2 admission."""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import duckdb
import pytest

from nbadb.contracts.public_table_value_projection import PublicTableValueProjectionV1
from nbadb.contracts.w2_operation import W2OperationPersistenceReceiptV1
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate import w2_operation_coordinator as coordinator_module
from nbadb.orchestrate.public_value_authority_store import (
    PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL,
    PUBLIC_VALUE_AUTHORITY_TABLES,
    PublicValueAuthorityStore,
    PublicValueAuthorityStoreResult,
)
from nbadb.orchestrate.raw_request_store import (
    RAW_REQUEST_AUTHORITY_TABLES,
    RawRequestAuthorityPersistenceReceiptV2,
    RawRequestAuthorityStore,
    logical_parameter_digests_by_provider_call,
)
from nbadb.orchestrate.w2_operation_coordinator import (
    W2OperationBuildInputsV1,
    W2OperationCoordinatorError,
    W2SourceCallAdmissionV1,
    W2SourceCallCandidateV1,
    coordinate_w2_source_call,
    verify_w2_source_call_admission,
)
from nbadb.orchestrate.w2_operation_store import (
    RAW_NBA_API_W2_OPERATION_TABLE,
    W2OperationStore,
)
from tests.unit.contracts.test_public_value_authority_adapter import _live_bundle
from tests.unit.contracts.test_raw_request_authority import (
    _static_bundle,
    _stats_fallback_bundle,
)
from tests.unit.contracts.test_raw_request_finalization import _aliased_stats_bundle
from tests.unit.contracts.test_w2_operation_builder import _valid_values


def _binding(values: dict[str, object]) -> LogicalCallReceiptBinding:
    bundle = cast("Any", values["raw_bundle"])
    selected = tuple(item for item in bundle.observations if item.lifecycle == "selected_terminal")
    assert len(selected) == 1
    observation = selected[0]
    routes = tuple(
        sorted(
            item.route_id
            for item in bundle.landings
            if item.observation_sha256 == observation.attempt.observation_sha256
        )
    )
    return LogicalCallReceiptBinding(
        logical_call_receipt_sha256=observation.logical_receipt_sha256,
        endpoint_name=routes[0].split(":", 1)[0],
        logical_parameters_sha256=observation.attempt.safe_parameters_sha256,
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
        result_route_ids=routes,
    )


def _aliased_binding() -> tuple[Any, LogicalCallReceiptBinding]:
    bundle = _aliased_stats_bundle()
    observation = bundle.observations[0]
    logical_by_call = logical_parameter_digests_by_provider_call(bundle)
    logical_parameters_sha256 = logical_by_call[observation.attempt.provider_call_sha256]
    routes = tuple(
        item.route_id
        for item in bundle.landings
        if item.observation_sha256 == observation.attempt.observation_sha256
    )
    binding = LogicalCallReceiptBinding(
        logical_call_receipt_sha256=cast("str", observation.logical_receipt_sha256),
        endpoint_name=routes[0].split(":", 1)[0],
        logical_parameters_sha256=logical_parameters_sha256,
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
        result_route_ids=tuple(sorted(routes)),
    )
    assert logical_parameters_sha256 != observation.attempt.safe_parameters_sha256
    return bundle, binding


def _candidate(
    connection: duckdb.DuckDBPyConnection,
    *,
    input_changes: dict[str, object] | None = None,
) -> tuple[W2SourceCallCandidateV1, PublicValueAuthorityStore, W2OperationStore]:
    values = dict(_valid_values())
    if input_changes:
        values.update(input_changes)
    bundle = cast("Any", values["raw_bundle"])
    raw_receipt = RawRequestAuthorityStore(connection).persist_bundle(bundle)
    inputs = W2OperationBuildInputsV1(**cast("Any", values))
    candidate = W2SourceCallCandidateV1(
        logical_call_binding=_binding(values),
        raw_authority_persistence_receipt=raw_receipt,
        expected_raw_authority_persistence_receipt_sha256=raw_receipt.receipt_sha256,
        operation_inputs=inputs,
    )
    return candidate, PublicValueAuthorityStore(connection), W2OperationStore(connection)


def _raw_rows(connection: duckdb.DuckDBPyConnection) -> dict[str, tuple[object, ...]]:
    result: dict[str, tuple[object, ...]] = {}
    for table in RAW_REQUEST_AUTHORITY_TABLES:
        columns = tuple(
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        )
        expression = ", ".join(f'"{name}"' for name in columns)
        row = connection.execute(
            f'SELECT COUNT(*), BIT_XOR(HASH({expression})) FROM "{table}"'
        ).fetchone()
        assert row is not None
        result[table] = tuple(row)
    return result


def _coordinate(
    candidate: W2SourceCallCandidateV1,
    public_store: PublicValueAuthorityStore,
    operation_store: W2OperationStore,
) -> W2SourceCallAdmissionV1:
    return coordinate_w2_source_call(
        candidate,
        public_value_store=public_store,
        operation_store=operation_store,
    )


def _verify(
    admission: W2SourceCallAdmissionV1,
    operation_store: W2OperationStore,
) -> W2SourceCallAdmissionV1:
    return verify_w2_source_call_admission(
        admission,
        expected_admission_sha256=admission.admission_sha256,
        expected_logical_call_receipt_sha256=admission.logical_call_receipt_sha256,
        expected_raw_authority_bundle_sha256=admission.raw_authority_bundle_sha256,
        expected_raw_authority_persistence_receipt_sha256=(
            admission.raw_authority_persistence_receipt_sha256
        ),
        expected_committed_staging_readback_count=(admission.committed_staging_readback_count),
        expected_committed_staging_readback_root_sha256=(
            admission.committed_staging_readback_root_sha256
        ),
        expected_operation_key_sha256=admission.operation_key_sha256,
        expected_operation_receipt_sha256=admission.operation_receipt_sha256,
        expected_w2_operation_persistence_receipt_sha256=(
            admission.w2_operation_persistence_receipt_sha256
        ),
        operation_store=operation_store,
    )


def test_fresh_admission_and_exact_replay_are_semantically_stable() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    raw_before = _raw_rows(connection)

    inserted = _coordinate(candidate, public_store, operation_store)
    replayed = _coordinate(candidate, public_store, operation_store)

    assert type(inserted) is W2SourceCallAdmissionV1
    assert inserted.persistence_receipt.replayed is False
    assert replayed.persistence_receipt.replayed is True
    assert replayed.admission_sha256 == inserted.admission_sha256
    assert replayed.operation == inserted.operation
    assert (
        replayed.persistence_receipt.persistence_receipt_sha256
        == inserted.persistence_receipt.persistence_receipt_sha256
    )
    assert _raw_rows(connection) == raw_before
    assert connection.execute(
        f'SELECT COUNT(*) FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"'
    ).fetchone() == (1,)


def test_admission_binds_logical_raw_staging_and_operation_identities() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)

    admission = _coordinate(candidate, public_store, operation_store)

    inputs = candidate.operation_inputs
    assert admission.logical_call_receipt_sha256 == (
        candidate.logical_call_binding.logical_call_receipt_sha256
    )
    assert admission.raw_authority_bundle_sha256 == cast("Any", inputs.raw_bundle).bundle_sha256
    assert admission.raw_authority_persistence_receipt_sha256 == (
        candidate.raw_authority_persistence_receipt.receipt_sha256
    )
    assert admission.committed_staging_readback_count == len(
        cast("tuple[object, ...]", inputs.committed_staging_readbacks)
    )
    assert admission.operation_key_sha256 == admission.operation.operation_key_sha256
    assert admission.operation_receipt_sha256 == admission.operation.operation_receipt_sha256
    assert admission.w2_operation_persistence_receipt_sha256 == (
        admission.persistence_receipt.persistence_receipt_sha256
    )
    replay = W2SourceCallAdmissionV1.from_canonical_bytes(admission.canonical_bytes())
    assert replay == admission


def test_aliased_league_game_log_binds_distinct_logical_and_provider_digests() -> None:
    bundle, binding = _aliased_binding()

    replayed = coordinator_module._preflight_logical_call(binding, bundle)

    assert replayed == binding
    assert replayed.logical_parameters_sha256 != (
        bundle.observations[0].attempt.safe_parameters_sha256
    )


@pytest.mark.parametrize("mutation", ("swapped", "foreign", "missing"))
def test_aliased_league_game_log_parameter_authority_mutations_fail_closed(
    mutation: str,
) -> None:
    bundle, binding = _aliased_binding()
    observation = bundle.observations[0]
    if mutation == "swapped":
        mutated_binding = replace(
            binding,
            logical_parameters_sha256=observation.attempt.safe_parameters_sha256,
        )
        mutated_bundle = bundle
    elif mutation == "foreign":
        mutated_binding = replace(binding, logical_parameters_sha256="f" * 64)
        mutated_bundle = bundle
    else:
        mutated_binding = binding
        missing = observation.model_copy(
            update={
                "logical_provider_parameter_binding_sha256": None,
                "logical_provider_parameter_binding_json": None,
            }
        )
        mutated_bundle = bundle.model_copy(update={"observations": (missing,)})

    with pytest.raises(
        W2OperationCoordinatorError,
        match="logical-call receipt|logical/provider parameter authority",
    ):
        coordinator_module._preflight_logical_call(
            mutated_binding,
            mutated_bundle,
        )


def test_reordered_or_noncanonical_admission_replay_is_rejected() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    admission = _coordinate(candidate, public_store, operation_store)
    reordered = dict(reversed(tuple(admission.to_dict().items())))

    with pytest.raises(W2OperationCoordinatorError, match="reordered"):
        W2SourceCallAdmissionV1.from_dict(reordered)
    noncanonical = json.dumps(admission.to_dict(), ensure_ascii=False).encode("utf-8")
    with pytest.raises(W2OperationCoordinatorError, match="not one exact canonical"):
        W2SourceCallAdmissionV1.from_canonical_bytes(noncanonical)


def test_read_only_verifier_replays_the_exact_committed_operation() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    admission = _coordinate(candidate, public_store, operation_store)
    before = connection.execute(
        f'SELECT COUNT(*) FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"'
    ).fetchone()

    verified = _verify(admission, operation_store)

    assert verified == admission
    assert verified is not admission
    assert (
        connection.execute(f'SELECT COUNT(*) FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"').fetchone()
        == before
    )


def test_read_only_verifier_checks_external_pins_before_store_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    admission = _coordinate(candidate, public_store, operation_store)
    touched_store = False

    def unexpected(**_kwargs: object) -> object:
        nonlocal touched_store
        touched_store = True
        raise AssertionError("store readback must not run")

    monkeypatch.setattr(operation_store, "_post_commit_readback", unexpected)
    with pytest.raises(W2OperationCoordinatorError, match="external resume authority"):
        verify_w2_source_call_admission(
            admission,
            expected_admission_sha256="0" * 64,
            expected_logical_call_receipt_sha256=admission.logical_call_receipt_sha256,
            expected_raw_authority_bundle_sha256=admission.raw_authority_bundle_sha256,
            expected_raw_authority_persistence_receipt_sha256=(
                admission.raw_authority_persistence_receipt_sha256
            ),
            expected_committed_staging_readback_count=(admission.committed_staging_readback_count),
            expected_committed_staging_readback_root_sha256=(
                admission.committed_staging_readback_root_sha256
            ),
            expected_operation_key_sha256=admission.operation_key_sha256,
            expected_operation_receipt_sha256=admission.operation_receipt_sha256,
            expected_w2_operation_persistence_receipt_sha256=(
                admission.w2_operation_persistence_receipt_sha256
            ),
            operation_store=operation_store,
        )
    assert touched_store is False


def test_read_only_verifier_rejects_staging_or_public_only_candidate() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    inputs = candidate.operation_inputs
    operation = coordinator_module._build_operation(inputs)
    public_store.persist_candidate(
        plan=inputs.plan,
        expected_plan_sha256=inputs.expected_plan_sha256,
        expected_raw_authority_bundle_sha256=inputs.expected_raw_authority_bundle_sha256,
        expected_ownership_receipt_sha256=inputs.expected_ownership_receipt_sha256,
        result_cell_schema_sha256=inputs.result_cell_schema_sha256,
        result_cell_rows=inputs.result_cell_rows,
        stats_lossless_schema_sha256=inputs.stats_lossless_schema_sha256,
        stats_lossless_rows=inputs.stats_lossless_rows,
        live_lossless_schema_sha256=inputs.live_lossless_schema_sha256,
        live_lossless_rows=inputs.live_lossless_rows,
        value_representation_schema_sha256=inputs.value_representation_schema_sha256,
        value_representation_rows=inputs.value_representation_rows,
        route_field_landing_schema_sha256=inputs.route_field_landing_schema_sha256,
        route_field_landing_rows=inputs.route_field_landing_rows,
    )
    synthetic_persistence = W2OperationPersistenceReceiptV1.build(
        operation=operation,
        post_commit_readback_row=operation.to_row(),
        replayed=False,
    )
    synthetic = W2SourceCallAdmissionV1.build(
        logical_call_receipt_sha256=candidate.logical_call_binding.logical_call_receipt_sha256,
        raw_authority_persistence_receipt_sha256=(
            candidate.raw_authority_persistence_receipt.receipt_sha256
        ),
        operation=operation,
        persistence_receipt=synthetic_persistence,
    )

    with pytest.raises(W2OperationCoordinatorError, match="durable operation readback"):
        _verify(synthetic, operation_store)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert RAW_NBA_API_W2_OPERATION_TABLE not in tables


def test_read_only_verifier_rejects_missing_or_changed_operation_row() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    admission = _coordinate(candidate, public_store, operation_store)
    connection.execute(f'DELETE FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"')

    with pytest.raises(W2OperationCoordinatorError, match="durable operation readback"):
        _verify(admission, operation_store)


def test_read_only_verifier_refuses_caller_transaction_without_mutation() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    admission = _coordinate(candidate, public_store, operation_store)
    connection.execute("CREATE TABLE verifier_sentinel(value BIGINT)")
    connection.execute("BEGIN TRANSACTION")
    connection.execute("INSERT INTO verifier_sentinel VALUES (9)")

    with pytest.raises(W2OperationCoordinatorError, match="durable operation readback"):
        _verify(admission, operation_store)

    connection.execute("COMMIT")
    assert connection.execute("SELECT * FROM verifier_sentinel").fetchall() == [(9,)]


def test_raw_receipt_foreign_type_and_bundle_mismatch_fail_before_public_write() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)

    for receipt in (
        cast("RawRequestAuthorityPersistenceReceiptV2", object()),
        replace(candidate.raw_authority_persistence_receipt, bundle_sha256="0" * 64),
    ):
        mutated = replace(candidate, raw_authority_persistence_receipt=receipt)
        with pytest.raises(W2OperationCoordinatorError, match="Raw persistence"):
            _coordinate(mutated, public_store, operation_store)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert not tables.intersection(PUBLIC_VALUE_AUTHORITY_TABLES)
    assert RAW_NBA_API_W2_OPERATION_TABLE not in tables


def test_independent_raw_receipt_replay_covers_stats_static_live_and_missing() -> None:
    bundles = (
        _stats_fallback_bundle("header_drift")[0],
        _stats_fallback_bundle("missing_result")[0],
        _static_bundle()[0],
        _live_bundle(),
    )
    for bundle in bundles:
        receipt = RawRequestAuthorityStore(duckdb.connect(":memory:")).persist_bundle(bundle)
        replay = coordinator_module._expected_raw_persistence_receipt(
            bundle,
            replayed=receipt.replayed,
        )
        assert replay == receipt
        assert replay.receipt_sha256 == receipt.receipt_sha256


def test_staging_pin_mismatch_duplicate_and_reorder_fail_before_public_write() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    inputs = candidate.operation_inputs
    readbacks = cast("tuple[object, ...]", inputs.committed_staging_readbacks)
    pins = cast("tuple[str, ...]", inputs.expected_committed_staging_readback_sha256s)
    variants = (
        replace(inputs, expected_committed_staging_readback_sha256s=("0" * 64,)),
        replace(
            inputs,
            committed_staging_readbacks=(readbacks[0], readbacks[0]),
            expected_committed_staging_readback_sha256s=(pins[0], pins[0]),
        ),
        replace(
            inputs,
            committed_staging_readbacks=tuple(reversed(readbacks)),
            expected_committed_staging_readback_sha256s=tuple(reversed(pins)) + ("0" * 64,),
        ),
    )
    for variant in variants:
        with pytest.raises(W2OperationCoordinatorError, match="staging readback"):
            _coordinate(replace(candidate, operation_inputs=variant), public_store, operation_store)


def test_public_commit_is_orphan_safe_when_operation_store_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    original_insert = operation_store._insert_operation

    def fail_operation(_operation: object) -> None:
        raise RuntimeError("secret-shaped-operation-failure")

    monkeypatch.setattr(operation_store, "_insert_operation", fail_operation)
    with pytest.raises(W2OperationCoordinatorError, match="operation persistence") as caught:
        _coordinate(candidate, public_store, operation_store)
    assert "secret-shaped" not in str(caught.value)
    assert connection.execute(
        f'SELECT COUNT(*) FROM "{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}"'
    ).fetchone() == (1,)

    monkeypatch.setattr(operation_store, "_insert_operation", original_insert)
    admission = _coordinate(candidate, public_store, operation_store)
    assert admission.persistence_receipt.replayed is False


def test_operation_commit_then_raise_recovers_only_through_exact_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    original_commit = operation_store._commit_transaction

    def commit_then_raise() -> None:
        original_commit()
        raise RuntimeError("secret-shaped-post-commit-failure")

    monkeypatch.setattr(operation_store, "_commit_transaction", commit_then_raise)
    with pytest.raises(W2OperationCoordinatorError, match="operation persistence") as caught:
        _coordinate(candidate, public_store, operation_store)
    assert "secret-shaped" not in str(caught.value)
    assert connection.execute(
        f'SELECT COUNT(*) FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"'
    ).fetchone() == (1,)

    monkeypatch.setattr(operation_store, "_commit_transaction", original_commit)
    replay = _coordinate(candidate, public_store, operation_store)
    assert replay.persistence_receipt.replayed is True


def test_foreign_operation_persistence_receipt_is_not_an_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    original = operation_store.persist_operation

    def foreign(*args: object, **kwargs: object) -> object:
        original(*args, **kwargs)  # type: ignore[arg-type]
        return object()

    monkeypatch.setattr(operation_store, "persist_operation", foreign)
    with pytest.raises(W2OperationCoordinatorError, match="foreign persistence"):
        _coordinate(candidate, public_store, operation_store)


def test_foreign_or_aliased_public_readback_is_never_promoted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    original = public_store.persist_candidate

    def aliased(**kwargs: object) -> PublicValueAuthorityStoreResult:
        original(**kwargs)
        inputs = candidate.operation_inputs
        authority = PublicTableValueProjectionV1(
            receipt=cast("Any", inputs.public_table_value_projection_receipt),
            projection=cast("Any", inputs.public_projection),
            partitions=cast("Any", inputs.public_partitions),
            items=cast("Any", inputs.public_items),
        )
        return PublicValueAuthorityStoreResult(authority=authority, inserted=False)

    monkeypatch.setattr(public_store, "persist_candidate", aliased)
    with pytest.raises(W2OperationCoordinatorError, match="retained W2 witnesses"):
        _coordinate(candidate, public_store, operation_store)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert RAW_NBA_API_W2_OPERATION_TABLE not in tables


def test_public_store_failure_is_sanitized_and_does_not_create_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)

    def hostile(**_kwargs: object) -> object:
        raise RuntimeError("authorization=never-expose-this")

    monkeypatch.setattr(public_store, "persist_candidate", hostile)
    with pytest.raises(W2OperationCoordinatorError, match="five-relation") as caught:
        _coordinate(candidate, public_store, operation_store)
    assert "authorization" not in str(caught.value)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert RAW_NBA_API_W2_OPERATION_TABLE not in tables


def test_caller_transaction_is_preserved_and_no_admission_is_returned() -> None:
    connection = duckdb.connect(":memory:")
    candidate, public_store, operation_store = _candidate(connection)
    connection.execute("CREATE TABLE sentinel(value BIGINT)")
    connection.execute("BEGIN TRANSACTION")
    connection.execute("INSERT INTO sentinel VALUES (7)")

    with pytest.raises(W2OperationCoordinatorError, match="five-relation"):
        _coordinate(candidate, public_store, operation_store)

    connection.execute("COMMIT")
    assert connection.execute("SELECT * FROM sentinel").fetchall() == [(7,)]


def test_coordinator_call_order_is_reconstruct_then_public_then_operation() -> None:
    source = Path(coordinator_module.__file__)
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "coordinate_w2_source_call"
    )
    calls: dict[str, int] = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "_build_operation":
            calls["build"] = node.lineno
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "persist_candidate":
            calls["public"] = node.lineno
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "persist_operation":
            calls["operation"] = node.lineno
    assert calls["build"] < calls["public"] < calls["operation"]
