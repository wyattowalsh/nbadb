from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from typing import cast
from unittest.mock import patch

import duckdb
import pytest

from nbadb.contracts.logical_provider_parameter_binding import (
    LogicalProviderParameterBindingV1,
)
from nbadb.contracts.raw_request_authority import (
    RawRequestAuthorityBundleV2,
)
from nbadb.orchestrate import raw_request_store as store_module
from nbadb.orchestrate.raw_request_store import (
    RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL,
    RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL,
    RAW_REQUEST_AUTHORITY_TABLES,
    RawRequestAuthorityPersistenceError,
    RawRequestAuthorityStore,
    RawRequestClosureCallV2,
    RawRequestManifestAuthorityV2,
    compile_raw_request_manifest_authority,
)
from tests.unit.contracts.test_raw_request_finalization import (
    _aliased_stats_bundle,
)
from tests.unit.orchestrate._raw_request_test_support import (
    raw_request_video_authority_bundle,
)

_HASHES = tuple(f"{value:064x}" for value in range(1, 32))


class _SyntheticCancellation(BaseException):
    """Test-only cancellation signal outside the ordinary Exception hierarchy."""


class _HostileNoteCancellation(BaseException):
    """Cancellation whose dynamic note hook must never receive production dispatch."""

    def __init__(self, message: str, sentinel: BaseException) -> None:
        super().__init__(message)
        self._sentinel = sentinel

    def add_note(self, note: str) -> None:
        raise self._sentinel


class _FaultInjectingConnection:
    """Forward to one real connection while injecting exact transaction-edge faults."""

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        interrupt_after_begin: dict[int, BaseException] | None = None,
        fail_rollback_calls: tuple[int, ...] = (),
        fail_sql_rollback_calls: tuple[int, ...] = (),
    ) -> None:
        self.connection = connection
        self.interrupt_after_begin = interrupt_after_begin or {}
        self.fail_rollback_calls = frozenset(fail_rollback_calls)
        self.fail_sql_rollback_calls = frozenset(fail_sql_rollback_calls)
        self.begin_calls = 0
        self.rollback_calls = 0
        self.sql_rollback_calls = 0
        self.close_calls = 0
        self.execute_after_close_calls = 0
        self.closed = False

    def __getattr__(self, name: str):
        return getattr(self.connection, name)

    def execute(self, query: str, *args, **kwargs):
        if self.closed:
            self.execute_after_close_calls += 1
        if query == "ROLLBACK":
            self.sql_rollback_calls += 1
            if self.sql_rollback_calls in self.fail_sql_rollback_calls:
                raise RuntimeError("synthetic SQL rollback failure")
            return self.connection.execute(query, *args, **kwargs)
        result = self.connection.execute(query, *args, **kwargs)
        if query == "BEGIN TRANSACTION":
            self.begin_calls += 1
            interruption = self.interrupt_after_begin.get(self.begin_calls)
            if interruption is not None:
                raise interruption
        return result

    def rollback(self) -> None:
        self.rollback_calls += 1
        if self.rollback_calls in self.fail_rollback_calls:
            raise RuntimeError("synthetic rollback failure")
        self.connection.rollback()

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        self.connection.close()


_INTERRUPTION_TYPES: tuple[type[BaseException], ...] = (
    KeyboardInterrupt,
    SystemExit,
    _SyntheticCancellation,
)


def _issue_test_manifest_authority(
    unsigned: RawRequestManifestAuthorityV2,
) -> RawRequestManifestAuthorityV2:
    """Exercise the production compiler capability around a synthetic unit denominator."""

    with patch.object(
        store_module,
        "_compile_raw_request_manifest_authority_impl",
        return_value=unsigned,
    ):
        return compile_raw_request_manifest_authority(
            None,  # type: ignore[arg-type]
            None,
            assurance_authority=None,  # type: ignore[arg-type]
        )


def _bundle(
    *,
    payload: object | None = None,
    retry_ordinal: int = 0,
    terminal: bool = True,
) -> RawRequestAuthorityBundleV2:
    return raw_request_video_authority_bundle(
        payload=payload,
        retry_ordinal=retry_ordinal,
        terminal=terminal,
    )


def _manifest_authority(
    bundle: RawRequestAuthorityBundleV2,
    **overrides: object,
) -> RawRequestManifestAuthorityV2:
    observation = bundle.observations[0]
    attempt = observation.attempt
    scope_sha256 = str(overrides.pop("scope_sha256", attempt.scope_sha256))
    planned_routes_only = bool(overrides.pop("planned_routes_only", False))
    route_ids = tuple(
        sorted(
            {
                landing.route_id
                for landing in bundle.landings
                if not planned_routes_only
                or landing.route_authority_kind == "staging_route_contract_v1"
            }
        )
    )
    route = next(item for item in bundle.landings if item.route_id == route_ids[0])
    endpoint_name = route.route_id.split(":", 1)[0]
    parameter_binding_json = observation.logical_provider_parameter_binding_json
    logical_parameters_sha256 = attempt.safe_parameters_sha256
    if parameter_binding_json is not None:
        logical_parameters_sha256 = LogicalProviderParameterBindingV1.from_canonical_bytes(
            parameter_binding_json.encode("utf-8")
        ).logical_parameters_sha256
    expected_call = RawRequestClosureCallV2.build(
        endpoint_name=endpoint_name,
        source_family=attempt.source_family,
        endpoint_id=attempt.endpoint_id,
        logical_parameters_sha256=logical_parameters_sha256,
        provider_parameters_sha256=attempt.safe_parameters_sha256,
        provider_request_sha256=attempt.provider_request_sha256,
        route_ids=route_ids,
        scope_sha256=scope_sha256,
    )
    values: dict[str, object] = {
        "source_sha": attempt.source_sha,
        "run_id": attempt.run_id,
        "run_attempt": attempt.run_attempt,
        "chain_id": attempt.chain_id,
        "lane_id": attempt.lane_id,
        "scope_sha256": scope_sha256,
        "route_authority_sha256": _HASHES[20],
        "request_closure_authority_sha256": _HASHES[21],
        "field_authority_sha256": _HASHES[22],
        "model_authority_sha256": _HASHES[23],
        "expected_calls": (expected_call,),
        "compiler_provenance_sha256": "0" * 64,
    }
    values.update(overrides)
    return _issue_test_manifest_authority(
        RawRequestManifestAuthorityV2(**values)  # type: ignore[arg-type]
    )


def _authority_with_calls(
    bundle: RawRequestAuthorityBundleV2,
    calls: tuple[RawRequestClosureCallV2, ...],
) -> RawRequestManifestAuthorityV2:
    base = _manifest_authority(bundle)
    ordered = tuple(sorted(calls, key=lambda item: item.logical_request_sha256))
    scope_sha256 = hashlib.sha256(
        json.dumps(
            {
                "schema_version": 2,
                "kind": "nbadb_raw_request_composite_scope_v2",
                "logical_requests": [
                    {
                        "logical_request_sha256": item.logical_request_sha256,
                        "scope_sha256": item.scope_sha256,
                    }
                    for item in ordered
                ],
            },
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return _issue_test_manifest_authority(
        RawRequestManifestAuthorityV2(
            source_sha=base.source_sha,
            run_id=base.run_id,
            run_attempt=base.run_attempt,
            chain_id=base.chain_id,
            lane_id=base.lane_id,
            scope_sha256=scope_sha256,
            route_authority_sha256=base.route_authority_sha256,
            request_closure_authority_sha256=base.request_closure_authority_sha256,
            field_authority_sha256=base.field_authority_sha256,
            model_authority_sha256=base.model_authority_sha256,
            expected_calls=ordered,
            compiler_provenance_sha256="0" * 64,
        )
    )


@pytest.fixture
def connection():
    conn = duckdb.connect(":memory:")
    try:
        yield conn
    finally:
        conn.close()


def _count(connection: duckdb.DuckDBPyConnection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _assert_no_open_transaction(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("BEGIN TRANSACTION")
    connection.execute("ROLLBACK")


def test_store_atomically_persists_and_reads_back_all_fixed_tables(connection) -> None:
    bundle = _bundle()

    receipt = RawRequestAuthorityStore(connection).persist_bundle(bundle)

    assert receipt.bundle_sha256 == bundle.bundle_sha256
    assert receipt.replayed is False
    assert receipt.object_count == receipt.observation_count == receipt.landing_count == 1
    assert receipt.occurrence_count == 0
    assert len(receipt.receipt_sha256) == 64
    assert tuple(_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES) == (
        1,
        1,
        0,
        1,
    )
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1
    assert (
        connection.execute(
            f'SELECT stored_payload FROM "{RAW_REQUEST_AUTHORITY_TABLES[0]}"'
        ).fetchone()[0]
        == bundle.objects[0].stored_payload
    )
    observed = connection.execute(
        f'SELECT observation_record_sha256 FROM "{RAW_REQUEST_AUTHORITY_TABLES[1]}"'
    ).fetchone()[0]
    assert observed == bundle.observations[0].observation_record_sha256
    observed_landing = connection.execute(
        f'SELECT landing_sha256 FROM "{RAW_REQUEST_AUTHORITY_TABLES[3]}"'
    ).fetchone()[0]
    assert observed_landing == bundle.landings[0].landing_sha256
    assert receipt.landing_inventory_sha256 != receipt.occurrence_inventory_sha256
    assert receipt.landing_rows_sha256 != receipt.occurrence_rows_sha256


def test_public_read_only_receipt_verifier_reconstructs_exact_database_bytes(connection) -> None:
    bundle = _bundle(
        payload={
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
            ]
        }
    )
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    before = tuple(_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES)

    rebuilt = store.verify_persisted_receipt(
        expected_bundle_sha256=bundle.bundle_sha256,
        expected_receipt_sha256=receipt.receipt_sha256,
    )

    assert rebuilt == bundle
    assert rebuilt is not bundle
    assert tuple(_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES) == before
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1


def test_public_read_only_receipt_verifier_rejects_mutated_row_and_journal(connection) -> None:
    bundle = _bundle()
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    connection.execute(
        f'UPDATE "{RAW_REQUEST_AUTHORITY_TABLES[3]}" SET observation_sha256 = ?',
        ["f" * 64],
    )

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="strict reconstruction|exact reconstructed rows|verification failed",
    ):
        store.verify_persisted_receipt(
            expected_bundle_sha256=bundle.bundle_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )

    connection.execute(
        f'UPDATE "{RAW_REQUEST_AUTHORITY_TABLES[3]}" SET observation_sha256 = ?',
        [bundle.landings[0].observation_sha256],
    )
    connection.execute(
        f'UPDATE "{RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL}" SET receipt_sha256 = ?',
        ["e" * 64],
    )
    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="exact reconstructed rows",
    ):
        store.verify_persisted_receipt(
            expected_bundle_sha256=bundle.bundle_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )


def test_public_read_only_receipt_verifier_refuses_caller_transaction_without_mutation(
    connection,
) -> None:
    bundle = _bundle()
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    before = connection.execute(
        f'SELECT * FROM "{RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL}"'
    ).fetchall()
    connection.execute("BEGIN TRANSACTION")

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="caller-owned transaction",
    ):
        store.verify_persisted_receipt(
            expected_bundle_sha256=bundle.bundle_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )

    assert (
        connection.execute(f'SELECT * FROM "{RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL}"').fetchall()
        == before
    )
    connection.execute("ROLLBACK")


def test_store_preserves_ordered_multi_landing_and_occurrence_inventory(connection) -> None:
    bundle = _bundle(
        payload={
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
            ]
        }
    )
    assert len(bundle.occurrences) == 1
    assert len(bundle.landings) == 2

    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    journal = connection.execute(
        f'SELECT landing_keys_json, landing_count FROM "{RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL}"'
    ).fetchone()

    assert receipt.occurrence_count == 1
    assert receipt.landing_count == 2
    assert json.loads(journal[0]) == [item.landing_sha256 for item in bundle.landings]
    assert journal[1] == 2
    assert tuple(_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES) == (
        1,
        1,
        1,
        2,
    )
    authority = _manifest_authority(bundle)
    manifest = store.advance_manifest(authority, (receipt,))
    assert manifest.landing_reference_count == 2
    assert manifest.delta_landing_reference_count == 2
    assert manifest.landing_inventory_sha256 == manifest.delta_landing_inventory_sha256
    assert manifest.landing_rows_sha256 == manifest.delta_landing_rows_sha256


def test_manifest_fixed_denominator_accepts_one_exact_typed_conditional_route(
    connection,
) -> None:
    bundle = _bundle(
        payload={
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
            ]
        }
    )
    fixed_routes = tuple(
        landing.route_id
        for landing in bundle.landings
        if landing.route_authority_kind == "staging_route_contract_v1"
    )
    conditional_routes = tuple(
        landing.route_id
        for landing in bundle.landings
        if landing.route_authority_kind == "conditional_staging_route_admission_v1"
    )
    assert len(fixed_routes) == len(conditional_routes) == 1
    authority = _manifest_authority(bundle, planned_routes_only=True)
    assert authority.expected_calls[0].route_ids == fixed_routes

    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    manifest = store.advance_manifest(authority, (receipt,), terminal=True)

    assert receipt.attempts[0].route_ids == tuple(sorted((*fixed_routes, *conditional_routes)))
    assert manifest.completed_request_count == manifest.expected_request_count == 1
    assert manifest.coverage_complete is manifest.terminal_sealed is manifest.is_complete is True


def test_closure_call_rejects_unproved_conditional_route_shape() -> None:
    bundle = _bundle(
        payload={
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
            ]
        }
    )
    call = _manifest_authority(bundle, planned_routes_only=True).expected_calls[0]
    forged = f"{call.endpoint_name}:stg_nba_api_lossless_result_cells:999"

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="unproved conditional route",
    ):
        call.validate_terminal_route_ids(tuple(sorted((*call.route_ids, forged))))


def test_manifest_readback_rejects_foreign_landing_and_row_digest(connection) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    landing_table = RAW_REQUEST_AUTHORITY_TABLES[3]
    connection.execute(
        f'UPDATE "{landing_table}" SET observation_sha256 = ?',
        ["f" * 64],
    )

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="strict reconstruction|exact reconstructed rows",
    ):
        store.advance_manifest(authority, (receipt,))

    connection.execute(
        f'UPDATE "{landing_table}" SET observation_sha256 = ?',
        [bundle.landings[0].observation_sha256],
    )
    forged_receipt = replace(receipt, landing_rows_sha256="e" * 64)
    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="differs from persisted bundle authority",
    ):
        store.advance_manifest(authority, (forged_receipt,))


def test_manifest_readback_rejects_reordered_resealed_landing_inventory(connection) -> None:
    bundle = _bundle(
        payload={
            "resultSets": [
                {"name": "Stats", "headers": ["A"], "rowSet": [[1]]},
            ]
        }
    )
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    reversed_ids = tuple(reversed([item.landing_sha256 for item in bundle.landings]))
    encoded = json.dumps(
        list(reversed_ids),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    reordered_digest = hashlib.sha256(encoded.encode()).hexdigest()
    forged_receipt = replace(receipt, landing_inventory_sha256=reordered_digest)
    connection.execute(
        f'UPDATE "{RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL}" '
        "SET landing_keys_json = ?, landing_inventory_sha256 = ?, receipt_sha256 = ?",
        [encoded, reordered_digest, forged_receipt.receipt_sha256],
    )

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="strict reconstruction",
    ):
        store.advance_manifest(authority, (forged_receipt,))


def test_identical_replay_is_noop_with_same_semantic_receipt(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()

    initial = store.persist_bundle(bundle)
    replay = store.persist_bundle(bundle)

    assert initial.replayed is False
    assert replay.replayed is True
    assert replay.receipt_sha256 == initial.receipt_sha256
    assert tuple(_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES) == (
        1,
        1,
        0,
        1,
    )
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1


def test_aliased_bundle_exact_four_readback_and_manifest_replay_are_idempotent(
    connection,
) -> None:
    bundle = _aliased_stats_bundle()
    store = RawRequestAuthorityStore(connection)
    authority = _manifest_authority(bundle)

    initial = store.persist_bundle(bundle)
    rebuilt = store.verify_persisted_receipt(
        expected_bundle_sha256=bundle.bundle_sha256,
        expected_receipt_sha256=initial.receipt_sha256,
    )
    initial_manifest = store.advance_manifest(authority, (initial,))
    replay = store.persist_bundle(bundle)
    replayed_manifest = store.advance_manifest(authority, (replay,))

    assert len(RAW_REQUEST_AUTHORITY_TABLES) == 4
    assert rebuilt == bundle
    assert rebuilt is not bundle
    assert rebuilt.observations[0].logical_provider_parameter_binding_json is not None
    assert replay.replayed is True
    assert replay.receipt_sha256 == initial.receipt_sha256
    assert replayed_manifest == initial_manifest
    assert tuple(_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES) == (
        len(bundle.objects),
        len(bundle.observations),
        len(bundle.occurrences),
        len(bundle.landings),
    )
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1


@pytest.mark.parametrize(
    ("column", "mutation"),
    (
        ("logical_provider_parameter_binding_sha256", "f" * 64),
        ("logical_provider_parameter_binding_json", "append_space"),
    ),
)
def test_aliased_bundle_readback_rejects_mutated_binding_authority(
    connection,
    column: str,
    mutation: str,
) -> None:
    bundle = _aliased_stats_bundle()
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    observation = bundle.observations[0]
    value = (
        cast("str", observation.logical_provider_parameter_binding_json) + " "
        if mutation == "append_space"
        else mutation
    )
    connection.execute(
        f'UPDATE "{RAW_REQUEST_AUTHORITY_TABLES[1]}" SET "{column}" = ?',
        [value],
    )

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="durable receipt verification failed",
    ):
        store.verify_persisted_receipt(
            expected_bundle_sha256=bundle.bundle_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )


def test_natural_replay_and_replayed_relabel_seal_one_canonical_root() -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    initial_connection = duckdb.connect(":memory:")
    replay_connection = duckdb.connect(":memory:")
    relabel_connection = duckdb.connect(":memory:")
    try:
        initial_store = RawRequestAuthorityStore(initial_connection)
        initial_receipt = initial_store.persist_bundle(bundle)
        initial_root = initial_store.advance_manifest(authority, (initial_receipt,))

        replay_store = RawRequestAuthorityStore(replay_connection)
        replay_store.persist_bundle(bundle)
        replayed_receipt = replay_store.persist_bundle(bundle)
        replayed_root = replay_store.advance_manifest(authority, (replayed_receipt,))

        relabel_store = RawRequestAuthorityStore(relabel_connection)
        relabel_receipt = relabel_store.persist_bundle(bundle)
        relabelled_root = relabel_store.advance_manifest(
            authority,
            (replace(relabel_receipt, replayed=True),),
        )
    finally:
        initial_connection.close()
        replay_connection.close()
        relabel_connection.close()

    assert replayed_receipt.replayed is True
    assert initial_root == replayed_root == relabelled_root
    assert initial_root.manifest_sha256 == replayed_root.manifest_sha256
    assert initial_root.receipt_inventory_sha256 == replayed_root.receipt_inventory_sha256
    assert (
        initial_root.delta_receipt_inventory_sha256 == replayed_root.delta_receipt_inventory_sha256
    )
    assert all(not receipt.replayed for receipt in replayed_root.receipts)


def test_manifest_store_seals_root_and_resume_copy_plus_delta(connection) -> None:
    initial_bundle = _bundle(retry_ordinal=0, terminal=False)
    delta_bundle = _bundle(retry_ordinal=1)
    authority = _manifest_authority(delta_bundle)
    initial_store = RawRequestAuthorityStore(connection)
    initial_receipt = initial_store.persist_bundle(initial_bundle)

    root = initial_store.advance_manifest(authority, (initial_receipt,))

    resumed_store = RawRequestAuthorityStore(connection)
    delta_receipt = resumed_store.persist_bundle(delta_bundle)
    child = resumed_store.advance_manifest(authority, (delta_receipt,))

    assert root.generation == 0
    assert root.delta_receipt_sha256s == (initial_receipt.receipt_sha256,)
    assert child.generation == 1
    assert child.parent_manifest_sha256 == root.manifest_sha256
    assert child.receipts == tuple(
        sorted((initial_receipt, delta_receipt), key=lambda item: item.receipt_sha256)
    )
    assert child.delta_receipt_sha256s == (delta_receipt.receipt_sha256,)
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 2


def test_manifest_store_resume_replay_returns_exact_committed_operation(connection) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    initial_receipt = store.persist_bundle(bundle)
    root = store.advance_manifest(authority, (initial_receipt,))

    replayed_receipt = RawRequestAuthorityStore(connection).persist_bundle(bundle)
    replayed_manifest = RawRequestAuthorityStore(connection).advance_manifest(
        authority,
        (replayed_receipt,),
    )

    assert replayed_receipt.replayed is True
    assert replayed_manifest == root
    assert replayed_manifest.generation == 0
    assert replayed_manifest.parent_manifest_sha256 is None
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1


def test_manifest_store_terminal_closeout_is_explicit_verified_zero_delta(
    connection,
) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    partial = store.advance_manifest(authority, (receipt,))

    terminal = store.advance_manifest(authority, (), terminal=True)

    assert partial.coverage_complete is True
    assert partial.terminal_sealed is partial.is_complete is False
    assert terminal.generation == partial.generation + 1
    assert terminal.parent_manifest_sha256 == partial.manifest_sha256
    assert terminal.receipts == partial.receipts
    assert terminal.delta_receipt_sha256s == ()
    assert terminal.coverage_complete is terminal.terminal_sealed is terminal.is_complete is True

    replayed = store.persist_bundle(bundle)
    replayed_partial = store.advance_manifest(authority, (replayed,))
    explicit_child = store.advance_manifest(authority, (replayed,), terminal=True)

    assert replayed.replayed is True
    assert replayed_partial == partial
    assert explicit_child.parent_manifest_sha256 == terminal.manifest_sha256
    assert explicit_child.delta_receipt_sha256s == ()
    assert explicit_child.coverage_complete is explicit_child.terminal_sealed is True
    assert explicit_child.is_complete is True
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 3


@pytest.mark.parametrize("new_attempt_terminal", [False, True])
def test_manifest_store_terminal_parent_rejects_new_incomplete_or_success_retry(
    connection,
    new_attempt_terminal: bool,
) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    store.advance_manifest(authority, (receipt,))
    terminal = store.advance_manifest(authority, (), terminal=True)
    delta_receipt = store.persist_bundle(_bundle(retry_ordinal=1, terminal=new_attempt_terminal))

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="terminal manifest cannot accept a new receipt delta",
    ):
        store.advance_manifest(authority, (delta_receipt,))

    assert terminal.terminal_sealed is terminal.is_complete is True
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 2


def test_manifest_store_terminal_closeout_rejects_missing_expected_call(
    connection,
) -> None:
    bundle = _bundle()
    base = _manifest_authority(bundle)
    second = RawRequestClosureCallV2.build(
        endpoint_name="BoxScoreSummaryV3",
        source_family="live",
        endpoint_id="BoxScoreSummaryV3",
        logical_parameters_sha256=_HASHES[24],
        provider_parameters_sha256=_HASHES[24],
        provider_request_sha256=_HASHES[25],
        route_ids=("live_box_score:stg_live_box_score_summary:0",),
        scope_sha256=_HASHES[26],
    )
    authority = _authority_with_calls(bundle, (*base.expected_calls, second))
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    partial = store.advance_manifest(authority, (receipt,))

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="terminal sealing rejects unresolved closure calls",
    ):
        store.advance_manifest(authority, (), terminal=True)

    assert partial.coverage_complete is False
    assert partial.unresolved_request_sha256s == (second.logical_request_sha256,)
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1


def test_manifest_store_rejects_post_persist_stored_payload_mutation(connection) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    connection.execute(
        f'UPDATE "{RAW_REQUEST_AUTHORITY_TABLES[0]}" SET stored_payload = ?',
        [b"not-a-deterministic-gzip-object"],
    )

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="strict reconstruction",
    ):
        store.advance_manifest(authority, (receipt,))

    assert RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL not in {
        str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()
    }


def test_manifest_store_rejects_foreign_scope_before_manifest_write(connection) -> None:
    bundle = _bundle()
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    authority = _manifest_authority(bundle, scope_sha256="f" * 64)

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="exact closure call",
    ):
        store.advance_manifest(authority, (receipt,))

    assert RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL not in {
        str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()
    }


def test_manifest_store_rejects_direct_resealed_caller_authority(connection) -> None:
    bundle = _bundle()
    issued = _manifest_authority(bundle)
    forged = replace(
        issued,
        route_authority_sha256="c" * 64,
        request_closure_authority_sha256="d" * 64,
        field_authority_sha256="e" * 64,
        model_authority_sha256="f" * 64,
    )
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="lacks current-process exact-compilation provenance",
    ):
        store.advance_manifest(forged, (receipt,), terminal=True)

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="lacks current-process exact-compilation provenance",
    ):
        store.advance_manifest(
            replace(issued, compiler_provenance_sha256="0" * 64),
            (receipt,),
            terminal=True,
        )
    assert RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL not in {
        str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()
    }


def test_manifest_authority_serialization_round_trips_compiler_provenance_and_rejects_mutation(
    connection,
) -> None:
    issued = _manifest_authority(_bundle())
    payload = issued.to_dict()

    assert payload["compiler_provenance_sha256"] == issued.compiler_provenance_sha256
    assert (
        json.loads(json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":")))
        == payload
    )
    assert store_module.validate_raw_request_manifest_authority(issued) is issued

    mutated = replace(issued, compiler_provenance_sha256="f" * 64)
    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="lacks current-process exact-compilation provenance",
    ):
        store_module.validate_raw_request_manifest_authority(mutated)


def test_manifest_store_rejects_tampered_parent_before_roll_forward(connection) -> None:
    initial_bundle = _bundle(retry_ordinal=0)
    delta_bundle = _bundle(retry_ordinal=1)
    authority = _manifest_authority(initial_bundle)
    store = RawRequestAuthorityStore(connection)
    initial_receipt = store.persist_bundle(initial_bundle)
    store.advance_manifest(authority, (initial_receipt,))
    delta_receipt = store.persist_bundle(delta_bundle)
    connection.execute(
        f'UPDATE "{RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL}" SET receipt_inventory_sha256 = ?',
        ["f" * 64],
    )

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="columns differ",
    ):
        store.advance_manifest(authority, (delta_receipt,))

    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1


def test_manifest_restore_rejects_missing_zero_inventory_public_table(connection) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    terminal = store.advance_manifest(authority, (receipt,), terminal=True)
    assert receipt.occurrence_count == 0
    connection.execute(f'DROP TABLE "{RAW_REQUEST_AUTHORITY_TABLES[2]}"')

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="public raw table schema drifted: raw_nba_api_result_occurrence",
    ):
        store.advance_manifest(authority, (), terminal=True)

    assert terminal.is_complete is True
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1


def test_manifest_restore_rejects_additive_public_table_column(connection) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    terminal = store.advance_manifest(authority, (receipt,), terminal=True)
    connection.execute(
        f'ALTER TABLE "{RAW_REQUEST_AUTHORITY_TABLES[3]}" ADD COLUMN injected VARCHAR'
    )

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match="public raw table schema drifted: raw_nba_api_observation_route_landing",
    ):
        store.advance_manifest(authority, (), terminal=True)

    assert terminal.is_complete is True
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1


@pytest.mark.parametrize(
    ("table_name", "error_label"),
    (
        (RAW_REQUEST_AUTHORITY_TABLES[0], "object"),
        (RAW_REQUEST_AUTHORITY_TABLES[3], "landing"),
    ),
)
def test_manifest_store_rejects_missing_persisted_inventory_before_roll_forward(
    connection,
    table_name: str,
    error_label: str,
) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    store.advance_manifest(authority, (receipt,))
    connection.execute(f'DELETE FROM "{table_name}"')

    with pytest.raises(
        RawRequestAuthorityPersistenceError,
        match=rf"missing persisted {error_label} inventory",
    ):
        store.advance_manifest(authority, (receipt,))

    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1


def test_existing_key_with_changed_public_row_fails_and_rolls_back(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    store.persist_bundle(bundle)
    observation_table = RAW_REQUEST_AUTHORITY_TABLES[1]
    connection.execute(
        f'UPDATE "{observation_table}" SET chain_id = ?',
        ["other-chain"],
    )

    with pytest.raises(RawRequestAuthorityPersistenceError, match="readback differs"):
        store.persist_bundle(bundle)

    assert (
        connection.execute(f'SELECT chain_id FROM "{observation_table}"').fetchone()[0]
        == "other-chain"
    )
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1


@pytest.mark.parametrize(
    "exception_type",
    _INTERRUPTION_TYPES,
    ids=("keyboard-interrupt", "system-exit", "synthetic-cancellation"),
)
def test_bundle_transaction_rolls_back_every_base_exception_and_retries_cleanly(
    connection: duckdb.DuckDBPyConnection,
    exception_type: type[BaseException],
) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    interruption = exception_type("interrupt after the first public-table insert")
    original_insert = RawRequestAuthorityStore._insert_frame  # noqa: SLF001
    call_count = 0

    def _interrupt_after_first_insert(self, contract, frame) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise interruption
        original_insert(self, contract, frame)

    with (
        patch.object(RawRequestAuthorityStore, "_insert_frame", _interrupt_after_first_insert),
        pytest.raises(exception_type) as raised,
    ):
        store.persist_bundle(bundle)

    assert raised.value is interruption
    existing = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
    assert set(RAW_REQUEST_AUTHORITY_TABLES).isdisjoint(existing)
    assert RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL not in existing
    assert RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL not in existing
    _assert_no_open_transaction(connection)

    receipt = store.persist_bundle(bundle)
    assert receipt.replayed is False
    assert tuple(_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES) == (
        1,
        1,
        0,
        1,
    )
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1


@pytest.mark.parametrize(
    "exception_type",
    _INTERRUPTION_TYPES,
    ids=("keyboard-interrupt", "system-exit", "synthetic-cancellation"),
)
def test_manifest_transaction_rolls_back_every_base_exception_and_retries_as_root(
    connection: duckdb.DuckDBPyConnection,
    exception_type: type[BaseException],
) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    interruption = exception_type("interrupt after the manifest insert")
    original_insert = RawRequestAuthorityStore._insert_manifest  # noqa: SLF001

    def _interrupt_after_insert(self, manifest, **kwargs) -> None:
        original_insert(self, manifest, **kwargs)
        raise interruption

    with (
        patch.object(RawRequestAuthorityStore, "_insert_manifest", _interrupt_after_insert),
        pytest.raises(exception_type) as raised,
    ):
        store.advance_manifest(authority, (receipt,))

    assert raised.value is interruption
    existing = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
    assert set(RAW_REQUEST_AUTHORITY_TABLES).issubset(existing)
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1
    assert RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL not in existing
    _assert_no_open_transaction(connection)

    root = store.advance_manifest(authority, (receipt,))
    assert root.generation == 0
    assert root.parent_manifest_sha256 is None
    assert root.delta_receipt_sha256s == (receipt.receipt_sha256,)
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1


def test_bundle_begin_effect_then_base_exception_is_cleaned_before_retry(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    interruption = _SyntheticCancellation("interrupt after bundle BEGIN takes effect")
    proxy = _FaultInjectingConnection(
        connection,
        interrupt_after_begin={1: interruption},
    )
    object.__setattr__(store, "_conn", proxy)

    with pytest.raises(_SyntheticCancellation) as raised:
        store.persist_bundle(bundle)

    assert raised.value is interruption
    assert proxy.begin_calls == proxy.rollback_calls == 1
    assert proxy.sql_rollback_calls == 0
    _assert_no_open_transaction(connection)
    assert set(RAW_REQUEST_AUTHORITY_TABLES).isdisjoint(
        {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
    )

    receipt = store.persist_bundle(bundle)
    assert receipt.replayed is False


def test_manifest_begin_effect_then_base_exception_is_cleaned_before_retry(connection) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    interruption = _SyntheticCancellation("interrupt after manifest BEGIN takes effect")
    proxy = _FaultInjectingConnection(
        connection,
        interrupt_after_begin={1: interruption},
    )
    object.__setattr__(store, "_conn", proxy)

    with pytest.raises(_SyntheticCancellation) as raised:
        store.advance_manifest(authority, (receipt,))

    assert raised.value is interruption
    assert proxy.begin_calls == proxy.rollback_calls == 1
    assert proxy.sql_rollback_calls == 0
    _assert_no_open_transaction(connection)
    assert RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL not in {
        str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()
    }

    root = store.advance_manifest(authority, (receipt,))
    assert root.generation == 0


def test_recovery_begin_effect_then_base_exception_cleans_and_skips_verifier(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    commit_interruption = _SyntheticCancellation("interrupt after durable commit")
    probe_interruption = _SyntheticCancellation("interrupt after recovery BEGIN takes effect")
    proxy = _FaultInjectingConnection(
        connection,
        interrupt_after_begin={2: probe_interruption},
    )
    object.__setattr__(store, "_conn", proxy)
    original_commit = RawRequestAuthorityStore._commit_transaction  # noqa: SLF001
    original_verify = RawRequestAuthorityStore._verify_rows  # noqa: SLF001
    verify_calls = 0

    def _interrupt_after_commit(self) -> None:
        original_commit(self)
        raise commit_interruption

    def _count_verify(self, contract, frame) -> None:
        nonlocal verify_calls
        verify_calls += 1
        original_verify(self, contract, frame)

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_after_commit),
        patch.object(RawRequestAuthorityStore, "_verify_rows", _count_verify),
        pytest.raises(_SyntheticCancellation) as raised,
    ):
        store.persist_bundle(bundle)

    assert raised.value is commit_interruption
    assert verify_calls == len(RAW_REQUEST_AUTHORITY_TABLES)
    assert proxy.begin_calls == 2
    assert proxy.rollback_calls == 2
    assert proxy.sql_rollback_calls == 1
    assert any("state probe failed" in note for note in commit_interruption.__notes__)
    _assert_no_open_transaction(connection)
    assert RawRequestAuthorityStore(connection).persist_bundle(bundle).replayed is True


def test_recovery_uses_sql_rollback_fallback_and_verifies_only_when_clean(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    interruption = _SyntheticCancellation("interrupt after durable commit")
    proxy = _FaultInjectingConnection(
        connection,
        fail_rollback_calls=(1, 2),
    )
    object.__setattr__(store, "_conn", proxy)
    original_commit = RawRequestAuthorityStore._commit_transaction  # noqa: SLF001
    original_verify = RawRequestAuthorityStore._verify_rows  # noqa: SLF001
    commit_calls = 0
    verify_calls = 0

    def _interrupt_after_commit(self) -> None:
        nonlocal commit_calls
        commit_calls += 1
        original_commit(self)
        raise interruption

    def _count_verify(self, contract, frame) -> None:
        nonlocal verify_calls
        verify_calls += 1
        original_verify(self, contract, frame)

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_after_commit),
        patch.object(RawRequestAuthorityStore, "_verify_rows", _count_verify),
        pytest.raises(_SyntheticCancellation) as raised,
    ):
        store.persist_bundle(bundle)

    assert raised.value is interruption
    assert commit_calls == 1
    assert verify_calls == 2 * len(RAW_REQUEST_AUTHORITY_TABLES)
    assert proxy.rollback_calls == 2
    assert proxy.sql_rollback_calls == 2
    assert proxy.close_calls == 0
    assert store._poisoned is False  # noqa: SLF001
    _assert_no_open_transaction(connection)
    assert RawRequestAuthorityStore(connection).persist_bundle(bundle).replayed is True


def test_recovery_poison_closes_after_both_cleanup_channels_fail(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    interruption = _SyntheticCancellation("interrupt after durable commit")
    proxy = _FaultInjectingConnection(
        connection,
        fail_rollback_calls=(1, 2),
        fail_sql_rollback_calls=(1, 2),
    )
    object.__setattr__(store, "_conn", proxy)
    original_commit = RawRequestAuthorityStore._commit_transaction  # noqa: SLF001
    original_verify = RawRequestAuthorityStore._verify_rows  # noqa: SLF001
    verify_calls = 0

    def _interrupt_after_commit(self) -> None:
        original_commit(self)
        raise interruption

    def _count_verify(self, contract, frame) -> None:
        nonlocal verify_calls
        verify_calls += 1
        original_verify(self, contract, frame)

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_after_commit),
        patch.object(RawRequestAuthorityStore, "_verify_rows", _count_verify),
        pytest.raises(_SyntheticCancellation) as raised,
    ):
        store.persist_bundle(bundle)

    assert raised.value is interruption
    assert verify_calls == len(RAW_REQUEST_AUTHORITY_TABLES)
    assert proxy.rollback_calls == proxy.sql_rollback_calls == 2
    assert proxy.close_calls == 1
    assert store._poisoned is True  # noqa: SLF001
    assert any("connection poisoned" in note for note in interruption.__notes__)
    with pytest.raises(RawRequestAuthorityPersistenceError, match="connection is poisoned"):
        store.persist_bundle(bundle)
    with pytest.raises(duckdb.ConnectionException):
        connection.execute("SELECT 1")


def test_waiting_writer_rechecks_poison_after_acquiring_global_lock(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    interruption = _SyntheticCancellation("interrupt after durable commit")
    proxy = _FaultInjectingConnection(
        connection,
        fail_rollback_calls=(1, 2),
        fail_sql_rollback_calls=(1, 2),
    )
    object.__setattr__(store, "_conn", proxy)
    original_commit = RawRequestAuthorityStore._commit_transaction  # noqa: SLF001
    original_require = RawRequestAuthorityStore._require_usable  # noqa: SLF001
    first_commit_completed = threading.Event()
    release_first_writer = threading.Event()
    second_writer_prechecked = threading.Event()
    errors: dict[str, BaseException] = {}
    second_thread: threading.Thread | None = None

    def _interrupt_after_commit(self) -> None:
        original_commit(self)
        first_commit_completed.set()
        assert release_first_writer.wait(timeout=5)
        raise interruption

    def _tracked_require(self) -> None:
        original_require(self)
        if threading.current_thread() is second_thread:
            second_writer_prechecked.set()

    def _run(label: str) -> None:
        try:
            store.persist_bundle(bundle)
        except BaseException as exc:
            errors[label] = exc

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_after_commit),
        patch.object(RawRequestAuthorityStore, "_require_usable", _tracked_require),
    ):
        first_thread = threading.Thread(target=_run, args=("first",))
        second_thread = threading.Thread(target=_run, args=("second",))
        first_thread.start()
        assert first_commit_completed.wait(timeout=5)
        second_thread.start()
        assert second_writer_prechecked.wait(timeout=5)
        release_first_writer.set()
        first_thread.join(timeout=5)
        second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors["first"] is interruption
    assert type(errors["second"]) is RawRequestAuthorityPersistenceError
    assert str(errors["second"]) == "raw-request authority store connection is poisoned"
    assert proxy.close_calls == 1
    assert proxy.execute_after_close_calls == 0


def test_ordinary_exception_is_publicly_wrapped_with_exact_cause_and_clean_retry(
    connection,
) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    original_error = RuntimeError("ordinary insert failure")
    proxy = _FaultInjectingConnection(
        connection,
        fail_rollback_calls=(1,),
    )
    object.__setattr__(store, "_conn", proxy)
    original_insert = RawRequestAuthorityStore._insert_frame  # noqa: SLF001
    insert_calls = 0

    def _fail_second_insert(self, contract, frame) -> None:
        nonlocal insert_calls
        insert_calls += 1
        if insert_calls == 2:
            raise original_error
        original_insert(self, contract, frame)

    with (
        patch.object(RawRequestAuthorityStore, "_insert_frame", _fail_second_insert),
        pytest.raises(RawRequestAuthorityPersistenceError, match="transaction failed") as raised,
    ):
        store.persist_bundle(bundle)

    assert raised.value.__cause__ is original_error
    assert proxy.rollback_calls == proxy.sql_rollback_calls == 1
    _assert_no_open_transaction(connection)
    assert store.persist_bundle(bundle).replayed is False


def test_recovery_verifier_failure_is_noted_without_masking_or_dirtying(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    interruption = _SyntheticCancellation("interrupt after durable commit")
    verifier_failure = _SyntheticCancellation("interrupt during recovery readback")
    original_commit = RawRequestAuthorityStore._commit_transaction  # noqa: SLF001
    original_verify = RawRequestAuthorityStore._verify_rows  # noqa: SLF001
    verify_calls = 0

    def _interrupt_after_commit(self) -> None:
        original_commit(self)
        raise interruption

    def _fail_first_recovery_verify(self, contract, frame) -> None:
        nonlocal verify_calls
        verify_calls += 1
        if verify_calls > len(RAW_REQUEST_AUTHORITY_TABLES):
            raise verifier_failure
        original_verify(self, contract, frame)

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_after_commit),
        patch.object(RawRequestAuthorityStore, "_verify_rows", _fail_first_recovery_verify),
        pytest.raises(_SyntheticCancellation) as raised,
    ):
        store.persist_bundle(bundle)

    assert raised.value is interruption
    assert verify_calls == len(RAW_REQUEST_AUTHORITY_TABLES) + 1
    assert any("committed outcome readback failed" in note for note in interruption.__notes__)
    _assert_no_open_transaction(connection)
    assert RawRequestAuthorityStore(connection).persist_bundle(bundle).replayed is True


def test_hostile_add_note_override_cannot_replace_original_interruption(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    sentinel = _SyntheticCancellation("hostile note sentinel")
    interruption = _HostileNoteCancellation("interrupt after durable commit", sentinel)
    original_commit = RawRequestAuthorityStore._commit_transaction  # noqa: SLF001

    def _interrupt_after_commit(self) -> None:
        original_commit(self)
        raise interruption

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_after_commit),
        pytest.raises(_HostileNoteCancellation) as raised,
    ):
        store.persist_bundle(bundle)

    assert raised.value is interruption
    assert raised.value is not sentinel
    assert interruption.__notes__
    _assert_no_open_transaction(connection)
    assert RawRequestAuthorityStore(connection).persist_bundle(bundle).replayed is True


@pytest.mark.parametrize(
    "exception_type",
    _INTERRUPTION_TYPES,
    ids=("keyboard-interrupt", "system-exit", "synthetic-cancellation"),
)
def test_bundle_post_commit_interruption_preserves_exception_and_retries_as_replay(
    connection: duckdb.DuckDBPyConnection,
    exception_type: type[BaseException],
) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    interruption = exception_type("interrupt immediately after bundle commit")
    original_commit = RawRequestAuthorityStore._commit_transaction  # noqa: SLF001

    def _interrupt_after_commit(self) -> None:
        original_commit(self)
        raise interruption

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_after_commit),
        pytest.raises(exception_type) as raised,
    ):
        store.persist_bundle(bundle)

    assert raised.value is interruption
    assert tuple(_count(connection, table) for table in RAW_REQUEST_AUTHORITY_TABLES) == (
        1,
        1,
        0,
        1,
    )
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1
    _assert_no_open_transaction(connection)

    replay = RawRequestAuthorityStore(connection).persist_bundle(bundle)
    assert replay.replayed is True
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1


@pytest.mark.parametrize(
    "exception_type",
    _INTERRUPTION_TYPES,
    ids=("keyboard-interrupt", "system-exit", "synthetic-cancellation"),
)
def test_manifest_post_commit_interruption_preserves_exact_committed_operation(
    connection: duckdb.DuckDBPyConnection,
    exception_type: type[BaseException],
) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    interruption = exception_type("interrupt immediately after manifest commit")
    original_commit = RawRequestAuthorityStore._commit_transaction  # noqa: SLF001

    def _interrupt_after_commit(self) -> None:
        original_commit(self)
        raise interruption

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_after_commit),
        pytest.raises(exception_type) as raised,
    ):
        store.advance_manifest(authority, (receipt,))

    assert raised.value is interruption
    committed = store._load_manifest_chain(authority)  # noqa: SLF001
    assert len(committed) == 1
    assert committed[0].generation == 0
    assert committed[0].parent_manifest_sha256 is None
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1
    _assert_no_open_transaction(connection)

    replay = RawRequestAuthorityStore(connection).advance_manifest(authority, (receipt,))
    assert replay == committed[0]
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 1


@pytest.mark.parametrize(
    "exception_type",
    _INTERRUPTION_TYPES,
    ids=("keyboard-interrupt", "system-exit", "synthetic-cancellation"),
)
def test_bundle_commit_boundary_interruption_before_sql_aborts_without_committing(
    connection: duckdb.DuckDBPyConnection,
    exception_type: type[BaseException],
) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    interruption = exception_type("interrupt before bundle commit executes")

    def _interrupt_before_commit(self) -> None:
        raise interruption

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_before_commit),
        pytest.raises(exception_type) as raised,
    ):
        store.persist_bundle(bundle)

    assert raised.value is interruption
    existing = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
    assert set(RAW_REQUEST_AUTHORITY_TABLES).isdisjoint(existing)
    assert RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL not in existing
    _assert_no_open_transaction(connection)

    receipt = store.persist_bundle(bundle)
    assert receipt.replayed is False


@pytest.mark.parametrize(
    "exception_type",
    _INTERRUPTION_TYPES,
    ids=("keyboard-interrupt", "system-exit", "synthetic-cancellation"),
)
def test_manifest_commit_boundary_interruption_before_sql_aborts_without_advancing(
    connection: duckdb.DuckDBPyConnection,
    exception_type: type[BaseException],
) -> None:
    bundle = _bundle()
    authority = _manifest_authority(bundle)
    store = RawRequestAuthorityStore(connection)
    receipt = store.persist_bundle(bundle)
    interruption = exception_type("interrupt before manifest commit executes")

    def _interrupt_before_commit(self) -> None:
        raise interruption

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_before_commit),
        pytest.raises(exception_type) as raised,
    ):
        store.advance_manifest(authority, (receipt,))

    assert raised.value is interruption
    existing = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
    assert RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL not in existing
    _assert_no_open_transaction(connection)

    root = store.advance_manifest(authority, (receipt,))
    assert root.generation == 0


def test_manifest_retry_resolves_original_generation_after_successor_commit(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    initial_bundle = _bundle(retry_ordinal=0, terminal=False)
    delta_bundle = _bundle(retry_ordinal=1)
    authority = _manifest_authority(delta_bundle)
    store = RawRequestAuthorityStore(connection)
    initial_receipt = store.persist_bundle(initial_bundle)
    interruption = _SyntheticCancellation("interrupt immediately after root commit")
    original_commit = RawRequestAuthorityStore._commit_transaction  # noqa: SLF001

    def _interrupt_after_commit(self) -> None:
        original_commit(self)
        raise interruption

    with (
        patch.object(RawRequestAuthorityStore, "_commit_transaction", _interrupt_after_commit),
        pytest.raises(_SyntheticCancellation) as raised,
    ):
        store.advance_manifest(authority, (initial_receipt,))
    assert raised.value is interruption

    root = store._load_manifest_chain(authority)[0]  # noqa: SLF001
    delta_receipt = store.persist_bundle(delta_bundle)
    child = store.advance_manifest(authority, (delta_receipt,))
    retry = store.advance_manifest(authority, (initial_receipt,))

    assert child.generation == 1
    assert retry == root
    assert retry.generation == 0
    assert _count(connection, RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL) == 2


def test_foreign_bundle_journal_collision_fails_closed(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    store.persist_bundle(bundle)
    connection.execute(
        f'UPDATE "{RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL}" '
        "SET occurrence_inventory_sha256 = ? WHERE bundle_sha256 = ?",
        ["f" * 64, bundle.bundle_sha256],
    )

    with pytest.raises(RawRequestAuthorityPersistenceError, match="journal readback differs"):
        store.persist_bundle(bundle)

    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1


def test_existing_journal_never_repairs_a_missing_public_row(connection) -> None:
    store = RawRequestAuthorityStore(connection)
    bundle = _bundle()
    store.persist_bundle(bundle)
    landing_table = RAW_REQUEST_AUTHORITY_TABLES[3]
    connection.execute(f'DELETE FROM "{landing_table}"')

    with pytest.raises(RawRequestAuthorityPersistenceError, match="readback differs"):
        store.persist_bundle(bundle)

    assert _count(connection, landing_table) == 0
    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 1


def test_preexisting_journal_type_drift_aborts_before_any_rows(connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE "{RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL}" (
            bundle_sha256 VARCHAR PRIMARY KEY,
            object_keys_json VARCHAR NOT NULL,
            observation_keys_json VARCHAR NOT NULL,
            occurrence_keys_json VARCHAR NOT NULL,
            landing_keys_json VARCHAR NOT NULL,
            object_count VARCHAR NOT NULL,
            observation_count BIGINT NOT NULL,
            occurrence_count BIGINT NOT NULL,
            landing_count BIGINT NOT NULL,
            object_inventory_sha256 VARCHAR NOT NULL,
            observation_inventory_sha256 VARCHAR NOT NULL,
            occurrence_inventory_sha256 VARCHAR NOT NULL,
            landing_inventory_sha256 VARCHAR NOT NULL,
            object_rows_sha256 VARCHAR NOT NULL,
            observation_rows_sha256 VARCHAR NOT NULL,
            occurrence_rows_sha256 VARCHAR NOT NULL,
            landing_rows_sha256 VARCHAR NOT NULL,
            receipt_sha256 VARCHAR NOT NULL
        )
        """
    )

    with pytest.raises(RawRequestAuthorityPersistenceError, match="journal schema drifted"):
        RawRequestAuthorityStore(connection).persist_bundle(_bundle())

    assert _count(connection, RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL) == 0
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert set(RAW_REQUEST_AUTHORITY_TABLES).isdisjoint(existing)


def test_preexisting_public_table_schema_drift_aborts_before_any_rows(connection) -> None:
    connection.execute(
        f'CREATE TABLE "{RAW_REQUEST_AUTHORITY_TABLES[0]}" (object_sha256 VARCHAR PRIMARY KEY)'
    )

    with pytest.raises(RawRequestAuthorityPersistenceError, match="schema drifted"):
        RawRequestAuthorityStore(connection).persist_bundle(_bundle())

    assert _count(connection, RAW_REQUEST_AUTHORITY_TABLES[0]) == 0
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert set(RAW_REQUEST_AUTHORITY_TABLES[1:]).isdisjoint(existing)
    assert RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL not in existing


def test_empty_bundle_is_valid_contract_but_not_a_persistence_event(connection) -> None:
    empty = RawRequestAuthorityBundleV2.build(
        objects=(),
        observations=(),
        occurrences=(),
        landings=(),
    )

    with pytest.raises(RawRequestAuthorityPersistenceError, match="empty observation"):
        RawRequestAuthorityStore(connection).persist_bundle(empty)

    assert (
        connection.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchone()[0]
        == 0
    )


def test_constructor_rejects_foreign_connection_type() -> None:
    with pytest.raises(TypeError, match="DuckDB connection"):
        RawRequestAuthorityStore(object())  # type: ignore[arg-type]
