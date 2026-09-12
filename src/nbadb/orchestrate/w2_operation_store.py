"""Atomic DuckDB storage for one mandatory public W2 operation row.

This boundary persists only ``raw_nba_api_w2_operation``.  It does not own
pipeline-journal success, the Raw Authority V2 exact-four relations, staging
registration, or any extraction side effect.  A successful call proves an
exact keyed row after the write transaction has committed.
"""

from __future__ import annotations

import hashlib
import threading
from contextlib import suppress
from typing import Never, cast

import duckdb
import polars as pl

from nbadb.contracts.w2_operation import (
    W2OperationPersistenceReceiptV1,
    W2OperationReceiptV1,
)
from nbadb.schemas.raw.nba_api_w2_operation import (
    RAW_NBA_API_W2_OPERATION_COLUMNS,
    RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR,
    RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
    RawNbaApiW2OperationSchema,
)

__all__ = [
    "RAW_NBA_API_W2_OPERATION_TABLE",
    "W2OperationStore",
    "W2OperationStoreError",
]


RAW_NBA_API_W2_OPERATION_TABLE = "raw_nba_api_w2_operation"

_WRITE_LOCK = threading.RLock()
_SHA256_LENGTH = 64


class W2OperationStoreError(RuntimeError):
    """The W2 operation row could not be persisted or read back exactly."""


def _fail(message: str) -> Never:
    raise W2OperationStoreError(message) from None


def _exact_sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _quote_identifier(value: str) -> str:
    # Every caller is module-owned; keep quoting local so no dynamic SQL value
    # can enter this persistence boundary.
    if type(value) is not str or not value or not value.replace("_", "a").isalnum():
        _fail("W2 operation SQL identifier is invalid")
    return f'"{value}"'


def _sql_type(descriptor_type: str) -> str:
    if descriptor_type == "int":
        return "BIGINT"
    if descriptor_type == "str":
        return "VARCHAR"
    _fail("W2 operation schema descriptor contains an unsupported type")


def _polars_type(descriptor_type: str) -> type[pl.DataType]:
    if descriptor_type == "int":
        return pl.Int64
    if descriptor_type == "str":
        return pl.String
    _fail("W2 operation schema descriptor contains an unsupported type")


def _exact_schema_descriptor() -> tuple[tuple[str, str, bool], ...]:
    descriptor = RAW_NBA_API_W2_OPERATION_SCHEMA_DESCRIPTOR
    if type(descriptor) is not tuple or any(
        type(item) is not tuple
        or len(item) != 3
        or type(item[0]) is not str
        or type(item[1]) is not str
        or item[1] not in {"int", "str"}
        or type(item[2]) is not bool
        or item[2]
        for item in descriptor
    ):
        _fail("W2 operation schema descriptor is not exact and non-nullable")
    if tuple(item[0] for item in descriptor) != RAW_NBA_API_W2_OPERATION_COLUMNS:
        _fail("W2 operation schema descriptor has a foreign column order")
    return descriptor


class W2OperationStore:
    """Persist exact W2 operation rows on one caller-owned DuckDB connection."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        if not isinstance(connection, duckdb.DuckDBPyConnection):
            raise TypeError("W2 operation store requires one DuckDB connection")
        self._connection = connection
        self._poisoned = False

    def _require_usable(self) -> None:
        if self._poisoned:
            _fail("W2 operation store transaction state is not proven clean")

    @staticmethod
    def _frame_for_operation(operation: W2OperationReceiptV1) -> pl.DataFrame:
        descriptor = _exact_schema_descriptor()
        schema = {name: _polars_type(dtype) for name, dtype, _nullable in descriptor}
        row = operation.to_row()
        try:
            frame = pl.DataFrame([row], schema=schema, orient="row", strict=True)
            validated = RawNbaApiW2OperationSchema.validate(frame)
        except Exception:
            _fail("W2 operation failed its exact public table schema")
        if (
            type(validated) is not pl.DataFrame
            or tuple(validated.columns) != RAW_NBA_API_W2_OPERATION_COLUMNS
            or dict(validated.schema) != schema
            or validated.to_dicts() != [row]
        ):
            _fail("W2 operation public schema validation changed the exact row")
        return validated

    @classmethod
    def _preflight_operation(
        cls,
        operation: W2OperationReceiptV1,
        *,
        expected_operation_receipt_sha256: str,
        expected_operation_key_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_w2_operation_schema_sha256: str,
    ) -> tuple[W2OperationReceiptV1, dict[str, object], bytes]:
        """Replay every external pin before issuing any database statement."""

        if type(operation) is not W2OperationReceiptV1:
            _fail("W2 operation persistence requires one exact operation DTO")
        operation_pin = _exact_sha256(
            expected_operation_receipt_sha256,
            label="expected W2 operation receipt",
        )
        key_pin = _exact_sha256(
            expected_operation_key_sha256,
            label="expected W2 operation key",
        )
        bundle_pin = _exact_sha256(
            expected_raw_authority_bundle_sha256,
            label="expected W2 Raw bundle",
        )
        schema_pin = _exact_sha256(
            expected_w2_operation_schema_sha256,
            label="expected W2 operation schema",
        )
        if schema_pin != RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256:
            _fail("expected W2 operation schema differs from the runtime public schema")
        try:
            row = operation.to_row()
            exact = W2OperationReceiptV1.from_row(
                row,
                expected_operation_receipt_sha256=operation_pin,
                expected_operation_key_sha256=key_pin,
                expected_raw_authority_bundle_sha256=bundle_pin,
                expected_w2_operation_schema_sha256=schema_pin,
            )
            canonical = exact.canonical_bytes()
        except Exception:
            _fail("W2 operation differs from its external authority pins")
        if exact != operation or exact.to_row() != row or exact.canonical_bytes() != canonical:
            _fail("W2 operation is not an exact deterministic DTO replay")
        cls._frame_for_operation(exact)
        return exact, row, canonical

    def _require_no_caller_transaction(self) -> None:
        # DuckDB aborts a caller-owned transaction when a nested BEGIN is
        # attempted.  Two consecutive autocommit statements receive distinct
        # transaction IDs, whereas an explicit caller transaction retains one
        # ID.  Refuse the latter before claiming transaction ownership so the
        # caller's work is neither aborted nor rolled back by this store.
        first = self._connection.execute("SELECT current_transaction_id()").fetchone()
        second = self._connection.execute("SELECT current_transaction_id()").fetchone()
        if (
            first is None
            or second is None
            or len(first) != 1
            or len(second) != 1
            or type(first[0]) is not int
            or type(second[0]) is not int
            or first[0] == second[0]
        ):
            _fail("W2 operation store refuses a caller-owned transaction")

    def _begin_transaction(self) -> None:
        """Begin after the caller-transaction gate and ownership marker."""

        self._connection.execute("BEGIN TRANSACTION")

    def _commit_transaction(self) -> None:
        """Commit through one narrow fault-injection boundary."""

        self._connection.execute("COMMIT")

    def _rollback_transaction(self) -> None:
        """Rollback through one narrow fault-injection boundary."""

        self._connection.rollback()

    def _rollback_owned_transaction(self) -> bool:
        try:
            self._rollback_transaction()
        except BaseException:
            try:
                self._connection.execute("ROLLBACK")
            except BaseException:
                return False
        return True

    def _probe_clean_transaction_state(self) -> bool:
        began = False
        try:
            self._connection.execute("BEGIN TRANSACTION")
            began = True
            self._connection.execute("ROLLBACK")
        except BaseException:
            if began:
                with suppress(BaseException):
                    self._connection.execute("ROLLBACK")
            return False
        return True

    def _restore_after_owned_failure(self) -> None:
        if self._rollback_owned_transaction():
            return
        # A commit hook may fail after COMMIT has completed.  In that case both
        # rollback forms correctly report that no transaction exists; a fresh
        # begin/rollback pair proves the caller connection is clean without
        # guessing whether the row committed.
        if not self._probe_clean_transaction_state():
            self._poisoned = True

    def _ensure_table(self) -> None:
        descriptor = _exact_schema_descriptor()
        definitions = [
            f"{_quote_identifier(name)} {_sql_type(dtype)} NOT NULL"
            for name, dtype, _nullable in descriptor
        ]
        definitions.extend(
            (
                'PRIMARY KEY ("operation_key_sha256")',
                'UNIQUE ("operation_receipt_sha256")',
            )
        )
        table = _quote_identifier(RAW_NBA_API_W2_OPERATION_TABLE)
        self._connection.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(definitions)})")
        self._require_table_contract()

    def _require_table_contract(self) -> None:
        descriptor = _exact_schema_descriptor()
        try:
            table_rows = self._connection.execute(
                """
                SELECT internal, temporary, has_primary_key, column_count,
                       index_count, check_constraint_count
                FROM duckdb_tables()
                WHERE database_name = current_database()
                  AND schema_name = current_schema()
                  AND table_name = ?
                """,
                [RAW_NBA_API_W2_OPERATION_TABLE],
            ).fetchall()
            column_rows = self._connection.execute(
                f"PRAGMA table_info('{RAW_NBA_API_W2_OPERATION_TABLE}')"
            ).fetchall()
            constraint_rows = self._connection.execute(
                """
                SELECT constraint_type, constraint_column_names
                FROM duckdb_constraints()
                WHERE database_name = current_database()
                  AND schema_name = current_schema()
                  AND table_name = ?
                """,
                [RAW_NBA_API_W2_OPERATION_TABLE],
            ).fetchall()
        except Exception:
            _fail("W2 operation public table contract cannot be inspected")

        expected_columns = tuple(
            (
                ordinal,
                name,
                _sql_type(dtype),
                True,
                None,
                name == "operation_key_sha256",
            )
            for ordinal, (name, dtype, _nullable) in enumerate(descriptor)
        )
        observed_columns = tuple(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]).upper(),
                bool(row[3]),
                row[4],
                bool(row[5]),
            )
            for row in column_rows
        )
        expected_constraints = sorted(
            [
                *(("NOT NULL", (name,)) for name, _dtype, _nullable in descriptor),
                ("PRIMARY KEY", ("operation_key_sha256",)),
                ("UNIQUE", ("operation_receipt_sha256",)),
            ]
        )
        observed_constraints = sorted(
            (
                str(row[0]),
                tuple(cast("list[object]", row[1])) if type(row[1]) is list else (),
            )
            for row in constraint_rows
        )
        expected_table = (
            False,
            False,
            True,
            len(descriptor),
            2,
            0,
        )
        if (
            len(table_rows) != 1
            or tuple(table_rows[0]) != expected_table
            or observed_columns != expected_columns
            or observed_constraints != expected_constraints
        ):
            _fail("W2 operation public table schema or constraints drifted")

    def _rows_for_key(self, operation_key_sha256: str) -> tuple[tuple[object, ...], ...]:
        columns = ", ".join(_quote_identifier(name) for name in RAW_NBA_API_W2_OPERATION_COLUMNS)
        rows = self._connection.execute(
            f"SELECT {columns} FROM {_quote_identifier(RAW_NBA_API_W2_OPERATION_TABLE)} "
            'WHERE "operation_key_sha256" = ?',
            [operation_key_sha256],
        ).fetchall()
        return tuple(tuple(row) for row in rows)

    def _keys_for_receipt(self, operation_receipt_sha256: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            f'SELECT "operation_key_sha256" FROM '
            f"{_quote_identifier(RAW_NBA_API_W2_OPERATION_TABLE)} "
            'WHERE "operation_receipt_sha256" = ?',
            [operation_receipt_sha256],
        ).fetchall()
        if any(len(row) != 1 or type(row[0]) is not str for row in rows):
            _fail("W2 operation receipt lookup returned a malformed identity")
        return tuple(cast("str", row[0]) for row in rows)

    @staticmethod
    def _row_mapping(values: tuple[object, ...]) -> dict[str, object]:
        if len(values) != len(RAW_NBA_API_W2_OPERATION_COLUMNS):
            _fail("W2 operation keyed row has a foreign column shape")
        descriptor = _exact_schema_descriptor()
        for value, (_name, dtype, _nullable) in zip(values, descriptor, strict=True):
            expected_type = int if dtype == "int" else str
            if type(value) is not expected_type:
                _fail("W2 operation keyed row has a foreign exact value type")
        return dict(zip(RAW_NBA_API_W2_OPERATION_COLUMNS, values, strict=True))

    @classmethod
    def _require_exact_row(
        cls,
        rows: tuple[tuple[object, ...], ...],
        *,
        operation: W2OperationReceiptV1,
        canonical_operation: bytes,
    ) -> dict[str, object]:
        if type(rows) is not tuple or len(rows) != 1 or type(rows[0]) is not tuple:
            _fail("W2 operation keyed readback is missing or ambiguous")
        row = cls._row_mapping(rows[0])
        try:
            replay = W2OperationReceiptV1.from_row(
                row,
                expected_operation_receipt_sha256=operation.operation_receipt_sha256,
                expected_operation_key_sha256=operation.operation_key_sha256,
                expected_raw_authority_bundle_sha256=operation.raw_authority_bundle_sha256,
                expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
            )
            readback_bytes = replay.canonical_bytes()
        except Exception:
            _fail("W2 operation keyed row failed exact semantic replay")
        if replay != operation or readback_bytes != canonical_operation:
            _fail("W2 operation keyed row differs from the admitted canonical row")
        return row

    def _insert_operation(self, operation: W2OperationReceiptV1) -> None:
        row = operation.to_row()
        columns = RAW_NBA_API_W2_OPERATION_COLUMNS
        placeholders = ", ".join("?" for _ in columns)
        self._connection.execute(
            f"INSERT INTO {_quote_identifier(RAW_NBA_API_W2_OPERATION_TABLE)} "
            f"({', '.join(_quote_identifier(name) for name in columns)}) "
            f"VALUES ({placeholders})",
            [row[name] for name in columns],
        )

    def _verify_transaction_row(
        self,
        *,
        operation: W2OperationReceiptV1,
        canonical_operation: bytes,
    ) -> dict[str, object]:
        rows = self._rows_for_key(operation.operation_key_sha256)
        receipt_keys = self._keys_for_receipt(operation.operation_receipt_sha256)
        if receipt_keys != (operation.operation_key_sha256,):
            _fail("W2 operation key or receipt identity collides")
        return self._require_exact_row(
            rows,
            operation=operation,
            canonical_operation=canonical_operation,
        )

    def _post_commit_readback(
        self,
        *,
        operation: W2OperationReceiptV1,
        canonical_operation: bytes,
    ) -> dict[str, object]:
        # Deliberately no BEGIN here: this is the independent durable readback
        # that the persistence receipt seals.
        self._require_table_contract()
        return self._verify_transaction_row(
            operation=operation,
            canonical_operation=canonical_operation,
        )

    @staticmethod
    def _build_persistence_receipt(
        *,
        operation: W2OperationReceiptV1,
        readback_row: dict[str, object],
        replayed: bool,
    ) -> W2OperationPersistenceReceiptV1:
        try:
            receipt = W2OperationPersistenceReceiptV1.build(
                operation=operation,
                post_commit_readback_row=readback_row,
                replayed=replayed,
            )
            replay = W2OperationPersistenceReceiptV1.from_row(
                receipt.to_row(),
                expected_persistence_receipt_sha256=receipt.persistence_receipt_sha256,
                expected_operation_key_sha256=operation.operation_key_sha256,
                expected_operation_receipt_sha256=operation.operation_receipt_sha256,
                expected_w2_operation_schema_sha256=operation.w2_operation_schema_sha256,
                expected_operation_row_sha256=hashlib.sha256(
                    operation.canonical_bytes()
                ).hexdigest(),
            )
        except Exception:
            _fail("W2 operation persistence receipt failed exact replay")
        if replay != receipt:
            _fail("W2 operation persistence receipt changed during exact replay")
        return replay

    def persist_operation(
        self,
        operation: W2OperationReceiptV1,
        *,
        expected_operation_receipt_sha256: str,
        expected_operation_key_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_w2_operation_schema_sha256: str,
    ) -> W2OperationPersistenceReceiptV1:
        """Validate, commit, read back, and seal one exact W2 operation row."""

        self._require_usable()
        exact, _row, canonical = self._preflight_operation(
            operation,
            expected_operation_receipt_sha256=expected_operation_receipt_sha256,
            expected_operation_key_sha256=expected_operation_key_sha256,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_w2_operation_schema_sha256=expected_w2_operation_schema_sha256,
        )

        replayed = False
        with _WRITE_LOCK:
            self._require_usable()
            owns_transaction = False
            try:
                try:
                    self._require_no_caller_transaction()
                    # Mark provisional ownership before BEGIN.  If the driver
                    # accepts BEGIN and then raises an interrupt before the
                    # helper returns, the outer BaseException path must still
                    # roll back this store-owned transaction.
                    owns_transaction = True
                    self._begin_transaction()
                    self._ensure_table()
                    keyed_rows = self._rows_for_key(exact.operation_key_sha256)
                    receipt_keys = self._keys_for_receipt(exact.operation_receipt_sha256)
                    if len(keyed_rows) > 1 or len(receipt_keys) > 1:
                        _fail("W2 operation key or receipt identity collides")
                    if keyed_rows:
                        if receipt_keys != (exact.operation_key_sha256,):
                            _fail("W2 operation key or receipt identity collides")
                        try:
                            self._require_exact_row(
                                keyed_rows,
                                operation=exact,
                                canonical_operation=canonical,
                            )
                        except W2OperationStoreError:
                            _fail("W2 operation key or receipt identity collides")
                        replayed = True
                    else:
                        if receipt_keys:
                            _fail("W2 operation key or receipt identity collides")
                        self._insert_operation(exact)
                        self._verify_transaction_row(
                            operation=exact,
                            canonical_operation=canonical,
                        )
                    self._commit_transaction()
                    owns_transaction = False
                except W2OperationStoreError:
                    raise
                except Exception:
                    _fail("W2 operation write transaction failed")
            except BaseException as interruption:
                if owns_transaction:
                    self._restore_after_owned_failure()
                if isinstance(interruption, Exception):
                    if isinstance(interruption, W2OperationStoreError):
                        raise interruption from None
                    _fail("W2 operation write transaction failed")
                raise

            try:
                readback = self._post_commit_readback(
                    operation=exact,
                    canonical_operation=canonical,
                )
            except Exception:
                _fail("W2 operation post-commit readback failed")
        return self._build_persistence_receipt(
            operation=exact,
            readback_row=readback,
            replayed=replayed,
        )
