from __future__ import annotations

import threading
from dataclasses import fields
from typing import cast

import duckdb
import pytest

from nbadb.contracts.w2_operation import (
    W2OperationPersistenceReceiptV1,
    W2OperationReceiptV1,
)
from nbadb.orchestrate.raw_request_store import RAW_REQUEST_AUTHORITY_TABLES
from nbadb.orchestrate.staging_map import STAGING_MAP
from nbadb.orchestrate.w2_operation_store import (
    RAW_NBA_API_W2_OPERATION_TABLE,
    W2OperationStore,
    W2OperationStoreError,
)
from nbadb.schemas.raw.nba_api_w2_operation import (
    RAW_NBA_API_W2_OPERATION_COLUMNS,
    RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR,
    RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
)
from tests.unit.contracts.test_raw_request_authority import _sha
from tests.unit.contracts.test_w2_operation_schema import _operation


class _TextSubclass(str):
    pass


class _ForeignOperation(W2OperationReceiptV1):
    pass


def _pins(operation: W2OperationReceiptV1) -> dict[str, str]:
    return {
        "expected_operation_receipt_sha256": operation.operation_receipt_sha256,
        "expected_operation_key_sha256": operation.operation_key_sha256,
        "expected_raw_authority_bundle_sha256": operation.raw_authority_bundle_sha256,
        "expected_w2_operation_schema_sha256": RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
    }


def _persist(
    store: W2OperationStore,
    operation: W2OperationReceiptV1,
) -> W2OperationPersistenceReceiptV1:
    return store.persist_operation(operation, **_pins(operation))


def _table_count(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM duckdb_tables()
        WHERE database_name = current_database()
          AND schema_name = current_schema()
          AND table_name = ?
        """,
        [RAW_NBA_API_W2_OPERATION_TABLE],
    ).fetchone()
    assert row is not None and type(row[0]) is int
    return row[0]


def _row_count(connection: duckdb.DuckDBPyConnection) -> int:
    row = connection.execute(f'SELECT COUNT(*) FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"').fetchone()
    assert row is not None and type(row[0]) is int
    return row[0]


def test_fresh_insert_and_exact_verified_replay_are_idempotent() -> None:
    connection = duckdb.connect(":memory:")
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:fresh")
    store = W2OperationStore(connection)

    inserted = _persist(store, operation)
    replayed = _persist(store, operation)

    assert inserted.replayed is False
    assert replayed.replayed is True
    assert inserted.persistence_receipt_sha256 == replayed.persistence_receipt_sha256
    assert inserted.operation_row_sha256 == replayed.operation_row_sha256
    assert _row_count(connection) == 1
    row = connection.execute(f'SELECT * FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"').fetchone()
    assert row == tuple(operation.to_row().values())


def test_created_table_has_exact_order_types_nullability_and_two_identities() -> None:
    connection = duckdb.connect(":memory:")
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:schema")
    _persist(W2OperationStore(connection), operation)

    observed_columns = connection.execute(
        f"PRAGMA table_info('{RAW_NBA_API_W2_OPERATION_TABLE}')"
    ).fetchall()
    expected_columns = [
        (
            ordinal,
            name,
            "BIGINT" if descriptor_type == "int" else "VARCHAR",
            True,
            None,
            name == "operation_key_sha256",
        )
        for ordinal, (name, descriptor_type, _nullable) in enumerate(
            RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR
        )
    ]
    assert observed_columns == expected_columns
    constraints = connection.execute(
        """
        SELECT constraint_type, constraint_column_names
        FROM duckdb_constraints()
        WHERE database_name = current_database()
          AND schema_name = current_schema()
          AND table_name = ?
        """,
        [RAW_NBA_API_W2_OPERATION_TABLE],
    ).fetchall()
    normalized = sorted((kind, tuple(names)) for kind, names in constraints)
    assert normalized == sorted(
        [
            *(("NOT NULL", (name,)) for name in RAW_NBA_API_W2_OPERATION_COLUMNS),
            ("PRIMARY KEY", ("operation_key_sha256",)),
            ("UNIQUE", ("operation_receipt_sha256",)),
        ]
    )


def test_same_key_with_different_canonical_semantics_is_a_collision() -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    first = _operation(provider_call_ordinal=0, bundle_marker="store:key:first")
    conflicting = _operation(provider_call_ordinal=0, bundle_marker="store:key:second")
    assert first.operation_key_sha256 == conflicting.operation_key_sha256
    assert first.canonical_bytes() != conflicting.canonical_bytes()
    _persist(store, first)

    with pytest.raises(W2OperationStoreError, match="collides"):
        _persist(store, conflicting)
    assert _row_count(connection) == 1


def test_same_receipt_under_a_different_key_is_a_collision() -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:receipt")
    _persist(store, operation)
    foreign_key = _sha("store:foreign-key")
    connection.execute(
        f'UPDATE "{RAW_NBA_API_W2_OPERATION_TABLE}" SET "operation_key_sha256" = ?',
        [foreign_key],
    )

    with pytest.raises(W2OperationStoreError, match="collides"):
        _persist(store, operation)
    assert connection.execute(
        f'SELECT "operation_key_sha256" FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"'
    ).fetchone() == (foreign_key,)


@pytest.mark.parametrize(
    "pin_name",
    [
        "expected_operation_receipt_sha256",
        "expected_operation_key_sha256",
        "expected_raw_authority_bundle_sha256",
        "expected_w2_operation_schema_sha256",
    ],
)
def test_external_pin_mismatch_fails_before_any_sql(
    pin_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    operation = _operation(provider_call_ordinal=0, bundle_marker=f"store:pin:{pin_name}")
    pins = _pins(operation)
    pins[pin_name] = _sha(f"wrong:{pin_name}")
    began = False

    def _unexpected_begin() -> None:
        nonlocal began
        began = True
        raise AssertionError("SQL must not run")

    monkeypatch.setattr(store, "_begin_transaction", _unexpected_begin)
    with pytest.raises(W2OperationStoreError):
        store.persist_operation(operation, **pins)
    assert began is False
    assert _table_count(connection) == 0


def test_bool_subclass_and_foreign_dto_fail_before_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:foreign")
    foreign = _ForeignOperation(
        **{item.name: getattr(operation, item.name) for item in fields(W2OperationReceiptV1)}
    )
    began = False

    def _unexpected_begin() -> None:
        nonlocal began
        began = True

    monkeypatch.setattr(store, "_begin_transaction", _unexpected_begin)
    for candidate, pins in (
        (cast("W2OperationReceiptV1", True), _pins(operation)),
        (foreign, _pins(operation)),
        (
            operation,
            {
                **_pins(operation),
                "expected_operation_key_sha256": _TextSubclass(operation.operation_key_sha256),
            },
        ),
    ):
        with pytest.raises(W2OperationStoreError):
            store.persist_operation(candidate, **pins)
    assert began is False
    assert _table_count(connection) == 0


def test_existing_table_schema_drift_fails_closed_without_replacing_it() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute(f'CREATE TABLE "{RAW_NBA_API_W2_OPERATION_TABLE}" (schema_version BIGINT)')
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:drift")

    with pytest.raises(W2OperationStoreError, match="drifted"):
        _persist(W2OperationStore(connection), operation)
    assert connection.execute(
        f"PRAGMA table_info('{RAW_NBA_API_W2_OPERATION_TABLE}')"
    ).fetchall() == [(0, "schema_version", "BIGINT", False, None, False)]


def test_missing_key_and_receipt_constraints_are_schema_drift() -> None:
    connection = duckdb.connect(":memory:")
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:constraints")
    _persist(W2OperationStore(connection), operation)
    connection.execute(
        f'ALTER TABLE "{RAW_NBA_API_W2_OPERATION_TABLE}" RENAME TO "w2_with_constraints"'
    )
    connection.execute(
        f'CREATE TABLE "{RAW_NBA_API_W2_OPERATION_TABLE}" AS SELECT * FROM "w2_with_constraints"'
    )
    connection.execute('DROP TABLE "w2_with_constraints"')

    with pytest.raises(W2OperationStoreError, match="drifted"):
        _persist(W2OperationStore(connection), operation)
    assert _row_count(connection) == 1


@pytest.mark.parametrize("interruption", [RuntimeError("private-row-value"), KeyboardInterrupt()])
def test_insert_interruption_rolls_back_and_keeps_connection_open(
    interruption: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:interrupt")
    original_insert = store._insert_operation

    def _insert_then_interrupt(value: W2OperationReceiptV1) -> None:
        original_insert(value)
        raise interruption

    monkeypatch.setattr(store, "_insert_operation", _insert_then_interrupt)
    expected_error = (
        W2OperationStoreError if isinstance(interruption, Exception) else KeyboardInterrupt
    )
    with pytest.raises(expected_error) as caught:
        _persist(store, operation)
    assert "private-row-value" not in str(caught.value)
    assert _table_count(connection) == 0
    assert connection.execute("SELECT 1").fetchone() == (1,)


def test_pre_commit_failure_rolls_back_and_restores_clean_transaction_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:pre-commit")

    def _failed_commit() -> None:
        raise RuntimeError("private-commit-detail")

    monkeypatch.setattr(store, "_commit_transaction", _failed_commit)
    with pytest.raises(W2OperationStoreError) as caught:
        _persist(store, operation)
    assert "private-commit-detail" not in str(caught.value)
    assert _table_count(connection) == 0
    connection.execute("BEGIN TRANSACTION")
    connection.execute("ROLLBACK")


def test_failure_after_actual_commit_is_fail_closed_but_recoverable_as_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:ambiguous-commit")
    original_commit = store._commit_transaction

    def _commit_then_fail() -> None:
        original_commit()
        raise RuntimeError("private-after-commit-detail")

    monkeypatch.setattr(store, "_commit_transaction", _commit_then_fail)
    with pytest.raises(W2OperationStoreError) as caught:
        _persist(store, operation)
    assert "private-after-commit-detail" not in str(caught.value)
    assert _row_count(connection) == 1

    monkeypatch.setattr(store, "_commit_transaction", original_commit)
    replay = _persist(store, operation)
    assert replay.replayed is True
    assert connection.execute("SELECT 1").fetchone() == (1,)


def test_store_does_not_rollback_a_caller_owned_transaction() -> None:
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE sentinel(value BIGINT)")
    connection.execute("BEGIN TRANSACTION")
    connection.execute("INSERT INTO sentinel VALUES (7)")
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:caller-txn")

    with pytest.raises(W2OperationStoreError):
        _persist(W2OperationStore(connection), operation)
    connection.execute("COMMIT")
    assert connection.execute("SELECT * FROM sentinel").fetchall() == [(7,)]
    assert _table_count(connection) == 0


def test_interrupt_after_begin_takes_effect_rolls_back_owned_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:begin-interrupt")
    original_begin = store._begin_transaction

    def _begin_then_interrupt() -> None:
        original_begin()
        raise KeyboardInterrupt()

    monkeypatch.setattr(store, "_begin_transaction", _begin_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        _persist(store, operation)
    assert _table_count(connection) == 0
    connection.execute("BEGIN TRANSACTION")
    connection.execute("ROLLBACK")


def test_post_commit_readback_serializes_same_connection_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    first_store = W2OperationStore(connection)
    second_store = W2OperationStore(connection)
    first = _operation(provider_call_ordinal=0, bundle_marker="store:serialized:first")
    second = _operation(provider_call_ordinal=1, bundle_marker="store:serialized:second")
    original_readback = first_store._post_commit_readback
    readback_started = threading.Event()
    release_readback = threading.Event()
    second_started = threading.Event()
    second_finished = threading.Event()
    failures: list[BaseException] = []

    def _blocked_readback(**kwargs: object) -> dict[str, object]:
        readback_started.set()
        if not release_readback.wait(timeout=5):
            raise AssertionError("test did not release the serialized readback")
        return original_readback(**kwargs)  # type: ignore[arg-type]

    def _run_first() -> None:
        try:
            _persist(first_store, first)
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    def _run_second() -> None:
        second_started.set()
        try:
            _persist(second_store, second)
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            second_finished.set()

    monkeypatch.setattr(first_store, "_post_commit_readback", _blocked_readback)
    first_thread = threading.Thread(target=_run_first)
    second_thread = threading.Thread(target=_run_second)
    first_thread.start()
    assert readback_started.wait(timeout=5)
    second_thread.start()
    assert second_started.wait(timeout=5)
    assert not second_finished.wait(timeout=0.1)
    release_readback.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert failures == []
    assert _row_count(connection) == 2


@pytest.mark.parametrize("mode", ["mutate", "delete", "duplicate"])
def test_post_commit_mutation_deletion_and_duplicate_ambiguity_fail_closed(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    operation = _operation(provider_call_ordinal=0, bundle_marker=f"store:readback:{mode}")
    original_commit = store._commit_transaction

    def _commit_then_tamper() -> None:
        original_commit()
        if mode == "mutate":
            connection.execute(
                f'UPDATE "{RAW_NBA_API_W2_OPERATION_TABLE}" SET "equality_root_sha256" = ?',
                [_sha("store:mutated-readback")],
            )
        elif mode == "delete":
            connection.execute(f'DELETE FROM "{RAW_NBA_API_W2_OPERATION_TABLE}"')
        else:
            connection.execute(
                f'ALTER TABLE "{RAW_NBA_API_W2_OPERATION_TABLE}" RENAME TO "w2_single"'
            )
            connection.execute(
                f'CREATE TABLE "{RAW_NBA_API_W2_OPERATION_TABLE}" AS SELECT * FROM "w2_single"'
            )
            connection.execute(
                f'INSERT INTO "{RAW_NBA_API_W2_OPERATION_TABLE}" SELECT * FROM "w2_single"'
            )
            connection.execute('DROP TABLE "w2_single"')

    monkeypatch.setattr(store, "_commit_transaction", _commit_then_tamper)
    with pytest.raises(W2OperationStoreError, match="post-commit readback failed"):
        _persist(store, operation)
    assert connection.execute("SELECT 1").fetchone() == (1,)


def test_injected_post_commit_readback_failure_is_sanitized_and_replayable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = duckdb.connect(":memory:")
    store = W2OperationStore(connection)
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:readback-failure")
    original_readback = store._post_commit_readback

    def _failed_readback(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("private-readback-row-value")

    monkeypatch.setattr(store, "_post_commit_readback", _failed_readback)
    with pytest.raises(W2OperationStoreError) as caught:
        _persist(store, operation)
    assert "private-readback-row-value" not in str(caught.value)
    assert _row_count(connection) == 1

    monkeypatch.setattr(store, "_post_commit_readback", original_readback)
    assert _persist(store, operation).replayed is True


def test_returned_persistence_receipt_replays_and_has_no_self_row_root_cycle() -> None:
    connection = duckdb.connect(":memory:")
    operation = _operation(provider_call_ordinal=0, bundle_marker="store:receipt-replay")
    receipt = _persist(W2OperationStore(connection), operation)
    replay = W2OperationPersistenceReceiptV1.from_row(
        receipt.to_row(),
        expected_persistence_receipt_sha256=receipt.persistence_receipt_sha256,
        expected_operation_key_sha256=operation.operation_key_sha256,
        expected_operation_receipt_sha256=operation.operation_receipt_sha256,
        expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
        expected_operation_row_sha256=receipt.operation_row_sha256,
    )
    assert replay == receipt
    assert "operation_row_sha256" not in RAW_NBA_API_W2_OPERATION_COLUMNS
    assert "persistence_receipt_sha256" not in RAW_NBA_API_W2_OPERATION_COLUMNS
    assert receipt.operation_row_sha256 not in operation.canonical_bytes().decode("utf-8")


def test_store_does_not_expand_raw_exact_four_or_staging_map() -> None:
    assert RAW_NBA_API_W2_OPERATION_TABLE not in RAW_REQUEST_AUTHORITY_TABLES
    assert RAW_NBA_API_W2_OPERATION_TABLE not in {entry.staging_key for entry in STAGING_MAP}
