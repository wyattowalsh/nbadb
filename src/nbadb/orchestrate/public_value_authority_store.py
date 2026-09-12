"""Atomic DuckDB storage for the five pre-operation W2 public relations.

This boundary deliberately stops before ``raw_nba_api_w2_operation`` and the
extraction journal.  It validates one value-projection candidate, commits all
five structured public relations together, then reconstructs the public-table
projection from an exact bundle-scoped readback.  Its private journal is only
an idempotency/collision guard; it is not a public or semantic receipt.
"""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Never, cast

import duckdb
import polars as pl

from nbadb.contracts.live_lossless_value_authority import (
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
    MAX_LIVE_LOSSLESS_RECORDS,
    LiveLosslessNodeRecordV1,
)
from nbadb.contracts.public_table_value_projection import (
    RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
    RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
    RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
    PublicTableValueProjectionV1,
    build_public_table_value_projection,
)
from nbadb.contracts.public_value_types import (
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.raw_request_authority import MAX_JSON_NODES
from nbadb.contracts.raw_result_cell_authority import RawNbaApiResultCellV2
from nbadb.contracts.route_field_landing_authority import (
    MAX_ROUTE_FIELD_LANDING_ROWS,
    RawNbaApiRouteFieldLandingV1,
)
from nbadb.contracts.stats_lossless_value_authority import (
    MAX_STATS_LOSSLESS_RECORDS,
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
    StatsLosslessRecordV1,
)
from nbadb.contracts.value_projection_plan import ValueProjectionPlanV1
from nbadb.schemas.raw.nba_api_live_lossless_node import RawNbaApiLiveLosslessNodeSchema
from nbadb.schemas.raw.nba_api_result_cell import RawNbaApiResultCellSchema
from nbadb.schemas.raw.nba_api_route_field_landing import (
    RawNbaApiRouteFieldLandingSchema,
)
from nbadb.schemas.raw.nba_api_stats_lossless_record import (
    RawNbaApiStatsLosslessRecordSchema,
)
from nbadb.schemas.raw.nba_api_value_representation import (
    RawNbaApiValueRepresentationSchema,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import pandera.polars as pa


__all__ = [
    "PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL",
    "PUBLIC_VALUE_AUTHORITY_TABLES",
    "PublicValueAuthorityPersistenceError",
    "PublicValueAuthorityStore",
    "PublicValueAuthorityStoreResult",
]


PUBLIC_VALUE_AUTHORITY_TABLES: Final = (
    "raw_nba_api_result_cell",
    "raw_nba_api_stats_lossless_record",
    "raw_nba_api_live_lossless_node",
    "raw_nba_api_value_representation",
    "raw_nba_api_route_field_landing",
)
PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL: Final = "_public_value_authority_candidate_journal"

_WRITE_LOCK = threading.RLock()
_JOURNAL_COLUMNS: Final = (
    "raw_authority_bundle_sha256",
    "candidate_json",
    "candidate_sha256",
)


class PublicValueAuthorityPersistenceError(ValueError):
    """The five-relation public-value candidate could not be proven exact."""


def _fail(message: str) -> Never:
    raise PublicValueAuthorityPersistenceError(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise PublicValueAuthorityPersistenceError(
            "public-value candidate is not bounded canonical JSON"
        ) from None


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _duckdb_type(dtype: pl.DataType) -> str:
    if dtype == pl.Int64:
        return "BIGINT"
    if dtype == pl.String:
        return "VARCHAR"
    _fail("public-value schema contains an unsupported logical type")


def _polars_schema(schema_type: type[pa.DataFrameModel]) -> dict[str, pl.DataType]:
    result: dict[str, pl.DataType] = {}
    for name, column in schema_type.to_schema().columns.items():
        dtype = column.dtype.type
        if dtype not in {pl.Int64, pl.String}:
            _fail("public-value schema contains an unsupported logical type")
        result[name] = dtype
    return result


def _exact_row(
    value: object,
    *,
    columns: tuple[str, ...],
    decoder: Callable[[object], object],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict or tuple(value) != columns:
        _fail(f"{label} row differs from its exact ordered schema")
    row = cast("dict[str, object]", value)
    try:
        decoded = decoder(row)
        replay = cast("Any", decoded).to_row()
    except Exception:
        raise PublicValueAuthorityPersistenceError(f"{label} row failed exact DTO replay") from None
    if type(replay) is not dict or replay != row or tuple(replay) != columns:
        _fail(f"{label} row changed during exact DTO replay")
    return row


@dataclass(frozen=True, slots=True)
class _RelationContract:
    table_name: str
    label: str
    key_column: str
    bundle_column: str | None
    schema_type: type[pa.DataFrameModel]
    schema_sha256: str
    decoder: Callable[[object], object]
    maximum_rows: int


@dataclass(frozen=True, slots=True)
class _PreparedRelation:
    contract: _RelationContract
    rows: tuple[dict[str, object], ...]
    frame: pl.DataFrame
    keys: tuple[str, ...]


def _contracts() -> tuple[_RelationContract, ...]:
    return (
        _RelationContract(
            PUBLIC_VALUE_AUTHORITY_TABLES[0],
            "result-cell",
            "cell_sha256",
            None,
            RawNbaApiResultCellSchema,
            RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
            RawNbaApiResultCellV2.from_row,
            MAX_JSON_NODES,
        ),
        _RelationContract(
            PUBLIC_VALUE_AUTHORITY_TABLES[1],
            "stats-lossless",
            "record_sha256",
            "raw_authority_bundle_sha256",
            RawNbaApiStatsLosslessRecordSchema,
            STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
            StatsLosslessRecordV1.from_row,
            MAX_STATS_LOSSLESS_RECORDS,
        ),
        _RelationContract(
            PUBLIC_VALUE_AUTHORITY_TABLES[2],
            "live-lossless",
            "record_sha256",
            "raw_authority_bundle_sha256",
            RawNbaApiLiveLosslessNodeSchema,
            LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
            LiveLosslessNodeRecordV1.from_row,
            MAX_LIVE_LOSSLESS_RECORDS,
        ),
        _RelationContract(
            PUBLIC_VALUE_AUTHORITY_TABLES[3],
            "value-representation",
            "assignment_sha256",
            "raw_authority_bundle_sha256",
            RawNbaApiValueRepresentationSchema,
            RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
            ValueRepresentationAssignmentV1.from_row,
            MAX_PUBLIC_VALUE_EXPECTED_UNITS,
        ),
        _RelationContract(
            PUBLIC_VALUE_AUTHORITY_TABLES[4],
            "route-field-landing",
            "landing_field_sha256",
            "raw_authority_bundle_sha256",
            RawNbaApiRouteFieldLandingSchema,
            RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
            RawNbaApiRouteFieldLandingV1.from_row,
            MAX_ROUTE_FIELD_LANDING_ROWS,
        ),
    )


def _prepare_relation(
    contract: _RelationContract,
    inventory: object,
) -> _PreparedRelation:
    if type(inventory) is not tuple:
        _fail(f"{contract.label} row inventory must be one exact tuple")
    if len(inventory) > contract.maximum_rows:
        _fail(f"{contract.label} row inventory exceeds its exact public bound")
    columns = tuple(contract.schema_type.to_schema().columns)
    rows = tuple(
        _exact_row(
            item,
            columns=columns,
            decoder=contract.decoder,
            label=contract.label,
        )
        for item in inventory
    )
    schema = _polars_schema(contract.schema_type)
    try:
        frame = pl.DataFrame(rows, schema=schema, orient="row", strict=True)
        validated = contract.schema_type.validate(frame)
    except Exception:
        raise PublicValueAuthorityPersistenceError(
            f"{contract.label} rows failed their exact public schema"
        ) from None
    if (
        type(validated) is not pl.DataFrame
        or validated.columns != list(schema)
        or dict(validated.schema) != schema
        or validated.to_dicts() != list(rows)
    ):
        _fail(f"{contract.label} schema validation changed exact row bytes")
    keys = tuple(cast("str", row[contract.key_column]) for row in rows)
    if len(keys) != len(set(keys)):
        _fail(f"{contract.label} row inventory repeats one primary key")
    return _PreparedRelation(contract=contract, rows=rows, frame=validated, keys=keys)


def _require_plan_row_order(
    plan: ValueProjectionPlanV1,
    prepared: tuple[_PreparedRelation, ...],
) -> None:
    source_contracts = (
        ("result_cell_v1", "cell_sha256"),
        ("stats_lossless_record_v1", "record_sha256"),
        ("live_lossless_node_v1", "source_item_sha256"),
    )
    for relation, (source_kind, identity_column) in zip(
        prepared[:3], source_contracts, strict=True
    ):
        expected = tuple(
            item.source_record_sha256
            for item in plan.source_record_plans
            if item.source_relation_kind == source_kind
        )
        actual = tuple(cast("str", row[identity_column]) for row in relation.rows)
        if actual != expected:
            _fail(f"{relation.contract.label} rows differ from the exact ordered plan inventory")
    assignment_keys = tuple(item.assignment_sha256 for item in plan.assignments)
    if prepared[3].keys != assignment_keys:
        _fail("value-representation rows differ from the exact ordered plan inventory")


@dataclass(frozen=True, slots=True)
class PublicValueAuthorityStoreResult:
    """Operational outcome plus the authority rebuilt from durable readback.

    This wrapper intentionally has no schema version, digest, or serialization
    method.  ``authority`` remains the semantic object; ``inserted`` only tells
    the caller whether this invocation created or verified the candidate.
    """

    authority: PublicTableValueProjectionV1
    inserted: bool

    def __post_init__(self) -> None:
        if type(self.authority) is not PublicTableValueProjectionV1:
            _fail("public-value store result has a foreign projection authority")
        if type(self.inserted) is not bool:
            _fail("public-value store result has a foreign insertion disposition")

    @property
    def replayed(self) -> bool:
        """Return whether an exact pre-existing candidate was verified."""

        return not self.inserted


class PublicValueAuthorityStore:
    """Persist one five-relation W2 candidate on a caller-owned connection."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        if not isinstance(connection, duckdb.DuckDBPyConnection):
            raise TypeError("public-value authority store requires a DuckDB connection")
        self._conn = connection
        self._poisoned = False

    def _require_usable(self) -> None:
        if self._poisoned:
            _fail("public-value authority store connection is poisoned")

    def _commit_transaction(self) -> None:
        """Commit through one narrow fault-injection boundary."""

        self._conn.execute("COMMIT")

    def _require_autocommit_authority(self) -> None:
        """Prove no transaction is already owned by the caller."""

        try:
            first = self._conn.execute("SELECT current_transaction_id()").fetchone()
            second = self._conn.execute("SELECT current_transaction_id()").fetchone()
        except Exception:
            raise PublicValueAuthorityPersistenceError(
                "public-value transaction ownership cannot be proven"
            ) from None
        if (
            first is None
            or second is None
            or len(first) != 1
            or len(second) != 1
            or type(first[0]) is not int
            or type(second[0]) is not int
            or first[0] == second[0]
        ):
            _fail("public-value store refuses a caller-owned transaction")

    def _begin_transaction(self) -> None:
        """Issue BEGIN through one narrow post-gate fault-injection boundary."""

        self._conn.execute("BEGIN TRANSACTION")

    @staticmethod
    def _add_note(interruption: BaseException, note: str) -> None:
        with suppress(BaseException):
            BaseException.add_note(interruption, note)

    def _rollback(self, interruption: BaseException) -> bool:
        try:
            self._conn.rollback()
        except BaseException as first:
            self._add_note(
                interruption,
                f"public-value rollback failed: {type(first).__name__}",
            )
        else:
            return True
        try:
            self._conn.execute("ROLLBACK")
        except BaseException as second:
            self._add_note(
                interruption,
                f"public-value SQL rollback failed: {type(second).__name__}",
            )
            return False
        return True

    def _poison(self, interruption: BaseException) -> None:
        self._poisoned = True
        self._add_note(interruption, "public-value connection was poisoned")
        with suppress(BaseException):
            self._conn.close()

    def _probe_clean_transaction_state(self) -> bool:
        began = False
        try:
            self._conn.execute("BEGIN TRANSACTION")
            began = True
            self._conn.execute("ROLLBACK")
        except BaseException:
            if began:
                with suppress(BaseException):
                    self._conn.execute("ROLLBACK")
            return False
        return True

    def _restore_after_owned_failure(self, interruption: BaseException) -> None:
        if self._rollback(interruption):
            return
        # BEGIN may have failed before taking effect, or a commit hook may have
        # failed after COMMIT.  A fresh begin/rollback pair distinguishes a
        # clean autocommit connection without guessing either outcome.
        if not self._probe_clean_transaction_state():
            self._poison(interruption)

    def _ensure_table(self, contract: _RelationContract) -> None:
        schema = contract.schema_type.to_schema()
        polars_schema = _polars_schema(contract.schema_type)
        definitions = [
            f'"{name}" {_duckdb_type(polars_schema[name])}'
            + ("" if column.nullable else " NOT NULL")
            for name, column in schema.columns.items()
        ]
        definitions.append(f'PRIMARY KEY ("{contract.key_column}")')
        self._conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{contract.table_name}" ({", ".join(definitions)})'
        )
        self._require_table(contract)

    def _require_table(self, contract: _RelationContract) -> None:
        schema = contract.schema_type.to_schema()
        polars_schema = _polars_schema(contract.schema_type)
        expected_columns = tuple(
            (
                ordinal,
                name,
                _duckdb_type(polars_schema[name]),
                not column.nullable or name == contract.key_column,
                None,
                name == contract.key_column,
            )
            for ordinal, (name, column) in enumerate(schema.columns.items())
        )
        expected_constraints = sorted(
            [
                *(
                    ("NOT NULL", (name,))
                    for name, column in schema.columns.items()
                    if not column.nullable
                ),
                ("PRIMARY KEY", (contract.key_column,)),
            ]
        )
        try:
            table_rows = self._conn.execute(
                """
                SELECT database_name, schema_name, internal, temporary,
                       has_primary_key, column_count, index_count,
                       check_constraint_count
                FROM duckdb_tables()
                WHERE table_name = ?
                  AND (database_name = current_database() OR temporary)
                """,
                [contract.table_name],
            ).fetchall()
            column_rows = self._conn.execute(
                f"PRAGMA table_info('{contract.table_name}')"
            ).fetchall()
            constraint_rows = self._conn.execute(
                """
                SELECT constraint_type, constraint_column_names
                FROM duckdb_constraints()
                WHERE database_name = current_database()
                  AND schema_name = current_schema()
                  AND table_name = ?
                """,
                [contract.table_name],
            ).fetchall()
            current = self._conn.execute("SELECT current_database(), current_schema()").fetchone()
        except Exception:
            raise PublicValueAuthorityPersistenceError(
                f"public-value table schema drifted: {contract.table_name}"
            ) from None
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
        observed_constraints = sorted(
            (
                str(row[0]),
                tuple(cast("list[object]", row[1])) if type(row[1]) is list else (),
            )
            for row in constraint_rows
        )
        expected_table_tail = (
            False,
            False,
            True,
            len(expected_columns),
            1,
            0,
        )
        if (
            current is None
            or len(current) != 2
            or len(table_rows) != 1
            or tuple(table_rows[0][:2]) != tuple(current)
            or tuple(table_rows[0][2:]) != expected_table_tail
            or observed_columns != expected_columns
            or observed_constraints != expected_constraints
        ):
            _fail(f"public-value table schema drifted: {contract.table_name}")

    def _ensure_journal(self) -> None:
        self._conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}" ('
            "raw_authority_bundle_sha256 VARCHAR PRIMARY KEY, "
            "candidate_json VARCHAR NOT NULL, "
            "candidate_sha256 VARCHAR NOT NULL)"
        )
        try:
            table_rows = self._conn.execute(
                """
                SELECT database_name, schema_name, internal, temporary,
                       has_primary_key, column_count, index_count,
                       check_constraint_count
                FROM duckdb_tables()
                WHERE table_name = ?
                  AND (database_name = current_database() OR temporary)
                """,
                [PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL],
            ).fetchall()
            column_rows = self._conn.execute(
                f"PRAGMA table_info('{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}')"
            ).fetchall()
            constraint_rows = self._conn.execute(
                """
                SELECT constraint_type, constraint_column_names
                FROM duckdb_constraints()
                WHERE database_name = current_database()
                  AND schema_name = current_schema()
                  AND table_name = ?
                """,
                [PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL],
            ).fetchall()
            current = self._conn.execute("SELECT current_database(), current_schema()").fetchone()
        except Exception:
            raise PublicValueAuthorityPersistenceError(
                "public-value candidate journal schema drifted"
            ) from None
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
        observed_constraints = sorted(
            (
                str(row[0]),
                tuple(cast("list[object]", row[1])) if type(row[1]) is list else (),
            )
            for row in constraint_rows
        )
        expected_columns = (
            (0, "raw_authority_bundle_sha256", "VARCHAR", True, None, True),
            (1, "candidate_json", "VARCHAR", True, None, False),
            (2, "candidate_sha256", "VARCHAR", True, None, False),
        )
        expected_constraints = sorted(
            [
                ("NOT NULL", ("raw_authority_bundle_sha256",)),
                ("NOT NULL", ("candidate_json",)),
                ("NOT NULL", ("candidate_sha256",)),
                ("PRIMARY KEY", ("raw_authority_bundle_sha256",)),
            ]
        )
        if (
            current is None
            or len(current) != 2
            or len(table_rows) != 1
            or tuple(table_rows[0][:2]) != tuple(current)
            or tuple(table_rows[0][2:]) != (False, False, True, 3, 1, 0)
            or observed_columns != expected_columns
            or observed_constraints != expected_constraints
        ):
            _fail("public-value candidate journal schema drifted")

    def _journal_row(self, bundle_sha256: str) -> tuple[object, ...] | None:
        rows = self._conn.execute(
            f"SELECT {', '.join(_JOURNAL_COLUMNS)} "
            f'FROM "{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}" '
            "WHERE raw_authority_bundle_sha256 = ?",
            [bundle_sha256],
        ).fetchall()
        if len(rows) > 1:
            _fail("public-value candidate journal is ambiguous")
        return None if not rows else tuple(rows[0])

    @staticmethod
    def _candidate_payload(
        *,
        plan: ValueProjectionPlanV1,
        prepared: tuple[_PreparedRelation, ...],
        authority: PublicTableValueProjectionV1,
    ) -> tuple[str, str]:
        relations = []
        for relation in prepared:
            relations.append(
                {
                    "table_name": relation.contract.table_name,
                    "schema_sha256": relation.contract.schema_sha256,
                    "row_count": len(relation.rows),
                    "ordered_keys": list(relation.keys),
                    "ordered_row_sha256s": [_sha256(row) for row in relation.rows],
                }
            )
        payload = {
            "schema_version": 1,
            "kind": "nbadb_public_value_authority_candidate_v1",
            "raw_authority_bundle_sha256": plan.raw_authority_bundle_sha256,
            "plan_sha256": plan.plan_sha256,
            "ownership_receipt_sha256": plan.ownership_receipt_sha256,
            "public_table_projection_receipt_sha256": authority.receipt.receipt_sha256,
            "relations": relations,
        }
        encoded = _canonical_bytes(payload).decode("utf-8")
        return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _existing_key_rows(
        self,
        relation: _PreparedRelation,
    ) -> dict[str, dict[str, object]]:
        if not relation.keys:
            return {}
        view = "_nbadb_public_value_candidate_keys"
        self._conn.register(view, pl.DataFrame({relation.contract.key_column: relation.keys}))
        columns = tuple(relation.contract.schema_type.to_schema().columns)
        try:
            rows = self._conn.execute(
                f"SELECT {', '.join(f'stored."{item}"' for item in columns)} "
                f'FROM "{relation.contract.table_name}" AS stored '
                f'INNER JOIN "{view}" AS expected '
                f'ON stored."{relation.contract.key_column}" = '
                f'expected."{relation.contract.key_column}"'
            ).fetchall()
        finally:
            self._conn.unregister(view)
        materialized = [
            dict(zip(columns, cast("tuple[object, ...]", tuple(row)), strict=True)) for row in rows
        ]
        return {cast("str", row[relation.contract.key_column]): row for row in materialized}

    def _scope_rows(
        self,
        relation: _PreparedRelation,
        *,
        bundle_sha256: str,
        observation_sha256s: tuple[str, ...],
    ) -> tuple[dict[str, object], ...]:
        columns = tuple(relation.contract.schema_type.to_schema().columns)
        selected = ", ".join(f'"{name}"' for name in columns)
        if relation.contract.bundle_column is not None:
            rows = self._conn.execute(
                f'SELECT {selected} FROM "{relation.contract.table_name}" '
                f'WHERE "{relation.contract.bundle_column}" = ?',
                [bundle_sha256],
            ).fetchall()
        elif observation_sha256s:
            view = "_nbadb_public_value_candidate_observations"
            self._conn.register(
                view,
                pl.DataFrame({"observation_sha256": observation_sha256s}),
            )
            try:
                rows = self._conn.execute(
                    f"SELECT {', '.join(f'stored."{name}"' for name in columns)} "
                    f'FROM "{relation.contract.table_name}" AS stored '
                    f'INNER JOIN "{view}" AS expected '
                    'ON stored."observation_sha256" = expected."observation_sha256"'
                ).fetchall()
            finally:
                self._conn.unregister(view)
        else:
            rows = []
        materialized = tuple(
            dict(zip(columns, cast("tuple[object, ...]", tuple(row)), strict=True)) for row in rows
        )
        return materialized

    def _exact_readback(
        self,
        prepared: tuple[_PreparedRelation, ...],
        *,
        bundle_sha256: str,
        observation_sha256s: tuple[str, ...],
    ) -> tuple[tuple[dict[str, object], ...], ...]:
        inventories: list[tuple[dict[str, object], ...]] = []
        for relation in prepared:
            self._require_table(relation.contract)
            scoped = self._scope_rows(
                relation,
                bundle_sha256=bundle_sha256,
                observation_sha256s=observation_sha256s,
            )
            by_key: dict[str, dict[str, object]] = {}
            for row in scoped:
                key = cast("str", row[relation.contract.key_column])
                if key in by_key:
                    _fail(f"{relation.contract.label} readback repeats one key")
                by_key[key] = row
            if set(by_key) != set(relation.keys):
                _fail(
                    f"{relation.contract.label} bundle-scoped readback is "
                    "missing, extra, or foreign"
                )
            ordered = tuple(by_key[key] for key in relation.keys)
            rebuilt = _prepare_relation(relation.contract, cast("object", ordered))
            if rebuilt.rows != relation.rows:
                _fail(f"{relation.contract.label} exact readback differs from candidate")
            inventories.append(rebuilt.rows)
        return tuple(inventories)

    @staticmethod
    def _build_projection(
        *,
        plan: ValueProjectionPlanV1,
        expected_plan_sha256: object,
        expected_raw_authority_bundle_sha256: object,
        expected_ownership_receipt_sha256: object,
        schema_sha256s: tuple[object, ...],
        rows: tuple[tuple[dict[str, object], ...], ...],
    ) -> PublicTableValueProjectionV1:
        try:
            return build_public_table_value_projection(
                plan=plan,
                expected_plan_sha256=expected_plan_sha256,
                expected_raw_authority_bundle_sha256=(expected_raw_authority_bundle_sha256),
                expected_ownership_receipt_sha256=expected_ownership_receipt_sha256,
                result_cell_schema_sha256=schema_sha256s[0],
                result_cell_rows=cast("object", rows[0]),
                stats_lossless_schema_sha256=schema_sha256s[1],
                stats_lossless_rows=cast("object", rows[1]),
                live_lossless_schema_sha256=schema_sha256s[2],
                live_lossless_rows=cast("object", rows[2]),
                value_representation_schema_sha256=schema_sha256s[3],
                value_representation_rows=cast("object", rows[3]),
                route_field_landing_schema_sha256=schema_sha256s[4],
                route_field_landing_rows=cast("object", rows[4]),
            )
        except Exception:
            raise PublicValueAuthorityPersistenceError(
                "public-value rows failed exact public-table projection"
            ) from None

    def _insert_relation(self, relation: _PreparedRelation) -> None:
        if not relation.rows:
            return
        view = "_nbadb_public_value_candidate_rows"
        self._conn.register(view, relation.frame)
        columns = tuple(relation.contract.schema_type.to_schema().columns)
        quoted = ", ".join(f'"{name}"' for name in columns)
        try:
            self._conn.execute(
                f'INSERT INTO "{relation.contract.table_name}" ({quoted}) '
                f'SELECT {quoted} FROM "{view}"'
            )
        finally:
            self._conn.unregister(view)

    def persist_candidate(
        self,
        *,
        plan: object,
        expected_plan_sha256: object,
        expected_raw_authority_bundle_sha256: object,
        expected_ownership_receipt_sha256: object,
        result_cell_schema_sha256: object,
        result_cell_rows: object,
        stats_lossless_schema_sha256: object,
        stats_lossless_rows: object,
        live_lossless_schema_sha256: object,
        live_lossless_rows: object,
        value_representation_schema_sha256: object,
        value_representation_rows: object,
        route_field_landing_schema_sha256: object,
        route_field_landing_rows: object,
    ) -> PublicValueAuthorityStoreResult:
        """Validate, atomically persist, and exact-read back one W2 candidate."""

        self._require_usable()
        if type(plan) is not ValueProjectionPlanV1:
            _fail("public-value persistence requires an exact projection plan DTO")
        exact_plan = plan
        inventories = (
            result_cell_rows,
            stats_lossless_rows,
            live_lossless_rows,
            value_representation_rows,
            route_field_landing_rows,
        )
        schema_sha256s = (
            result_cell_schema_sha256,
            stats_lossless_schema_sha256,
            live_lossless_schema_sha256,
            value_representation_schema_sha256,
            route_field_landing_schema_sha256,
        )
        contracts = _contracts()
        if schema_sha256s != tuple(item.schema_sha256 for item in contracts):
            _fail("public-value schema pins differ from the frozen exact five-relation contract")
        prepared = tuple(
            _prepare_relation(contract, inventory)
            for contract, inventory in zip(contracts, inventories, strict=True)
        )
        _require_plan_row_order(exact_plan, prepared)
        candidate_rows = tuple(item.rows for item in prepared)
        candidate_authority = self._build_projection(
            plan=exact_plan,
            expected_plan_sha256=expected_plan_sha256,
            expected_raw_authority_bundle_sha256=(expected_raw_authority_bundle_sha256),
            expected_ownership_receipt_sha256=expected_ownership_receipt_sha256,
            schema_sha256s=schema_sha256s,
            rows=candidate_rows,
        )
        if (
            exact_plan.plan_sha256 != expected_plan_sha256
            or exact_plan.raw_authority_bundle_sha256 != expected_raw_authority_bundle_sha256
            or exact_plan.ownership_receipt_sha256 != expected_ownership_receipt_sha256
        ):
            _fail("public-value projection plan differs from its external pins")
        bundle_sha256 = exact_plan.raw_authority_bundle_sha256
        observation_sha256s = tuple(
            item.observation_sha256 for item in exact_plan.ownership_observations
        )
        if len(observation_sha256s) != len(set(observation_sha256s)):
            _fail("public-value projection plan repeats one observation identity")
        candidate_json, candidate_sha256 = self._candidate_payload(
            plan=exact_plan,
            prepared=prepared,
            authority=candidate_authority,
        )
        expected_journal = (bundle_sha256, candidate_json, candidate_sha256)

        inserted = False
        with _WRITE_LOCK:
            self._require_usable()
            active_transaction = False
            try:
                try:
                    self._require_autocommit_authority()
                    active_transaction = True
                    self._begin_transaction()
                    for relation in prepared:
                        self._ensure_table(relation.contract)
                    self._ensure_journal()
                    existing_journal = self._journal_row(bundle_sha256)
                    if existing_journal is not None and existing_journal != expected_journal:
                        _fail("public-value candidate collides with persisted bundle authority")

                    existing_by_relation = tuple(
                        self._existing_key_rows(relation) for relation in prepared
                    )
                    if existing_journal is None:
                        if any(existing_by_relation):
                            _fail("public-value candidate has partial pre-existing keyed state")
                        scoped = tuple(
                            self._scope_rows(
                                relation,
                                bundle_sha256=bundle_sha256,
                                observation_sha256s=observation_sha256s,
                            )
                            for relation in prepared
                        )
                        if any(scoped):
                            _fail("public-value candidate has partial bundle-scoped state")
                        for relation in prepared:
                            self._insert_relation(relation)
                        self._conn.execute(
                            f'INSERT INTO "{PUBLIC_VALUE_AUTHORITY_CANDIDATE_JOURNAL}" '
                            f"({', '.join(_JOURNAL_COLUMNS)}) VALUES (?, ?, ?)",
                            list(expected_journal),
                        )
                        inserted = True
                    else:
                        for relation, observed in zip(prepared, existing_by_relation, strict=True):
                            if set(observed) != set(relation.keys) or any(
                                observed[key] != row
                                for key, row in zip(relation.keys, relation.rows, strict=True)
                            ):
                                _fail(
                                    f"{relation.contract.label} replay differs from "
                                    "persisted keyed rows"
                                )
                    readback_rows = self._exact_readback(
                        prepared,
                        bundle_sha256=bundle_sha256,
                        observation_sha256s=observation_sha256s,
                    )
                    transactional_authority = self._build_projection(
                        plan=exact_plan,
                        expected_plan_sha256=expected_plan_sha256,
                        expected_raw_authority_bundle_sha256=(expected_raw_authority_bundle_sha256),
                        expected_ownership_receipt_sha256=(expected_ownership_receipt_sha256),
                        schema_sha256s=schema_sha256s,
                        rows=readback_rows,
                    )
                    if transactional_authority != candidate_authority:
                        _fail("public-value transactional readback changed the projection")
                    if self._journal_row(bundle_sha256) != expected_journal:
                        _fail("public-value candidate journal readback differs")
                    self._commit_transaction()
                    active_transaction = False
                except PublicValueAuthorityPersistenceError:
                    raise
                except Exception:
                    raise PublicValueAuthorityPersistenceError(
                        "public-value candidate transaction failed"
                    ) from None
            except BaseException as interruption:
                if active_transaction:
                    self._restore_after_owned_failure(interruption)
                raise

            try:
                if self._journal_row(bundle_sha256) != expected_journal:
                    _fail("public-value post-commit journal readback differs")
                committed_rows = self._exact_readback(
                    prepared,
                    bundle_sha256=bundle_sha256,
                    observation_sha256s=observation_sha256s,
                )
                committed_authority = self._build_projection(
                    plan=exact_plan,
                    expected_plan_sha256=expected_plan_sha256,
                    expected_raw_authority_bundle_sha256=(expected_raw_authority_bundle_sha256),
                    expected_ownership_receipt_sha256=expected_ownership_receipt_sha256,
                    schema_sha256s=schema_sha256s,
                    rows=committed_rows,
                )
            except PublicValueAuthorityPersistenceError:
                raise
            except Exception:
                raise PublicValueAuthorityPersistenceError(
                    "public-value post-commit readback failed"
                ) from None
            if committed_authority != candidate_authority:
                _fail("public-value post-commit projection differs from candidate")
        return PublicValueAuthorityStoreResult(
            authority=committed_authority,
            inserted=inserted,
        )
