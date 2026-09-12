from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import duckdb
from loguru import logger
from sqlalchemy import Engine, text
from sqlmodel import Session, SQLModel, create_engine

from nbadb.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    import duckdb as _duckdb_type

_DUCKDB_LOCK_ERROR_FRAGMENT = "Could not set lock on file"
_DUCKDB_LOCK_RETRY_ATTEMPTS = 4
_DUCKDB_LOCK_RETRY_BASE_DELAY_SECONDS = 0.5

_TRANSFORM_OUTPUT_AUTHORITY_TABLE = "_transform_output_disposition_authority"
_TRANSFORM_OUTPUT_RECEIPT_TABLE = "_transform_output_materialization_receipts"
_TRANSFORM_OUTPUT_COMMITMENT_TABLE = "_transform_output_operation_commitments"
_TRANSFORM_OUTPUT_AUTHORITY_TABLES = (
    _TRANSFORM_OUTPUT_AUTHORITY_TABLE,
    _TRANSFORM_OUTPUT_RECEIPT_TABLE,
    _TRANSFORM_OUTPUT_COMMITMENT_TABLE,
)
_TRANSFORM_OUTPUT_AUTHORITY_INSTALL_LOCK = threading.RLock()

_AUTHORITY_ENVELOPE_MAX_BYTES = 134_217_728
_MATERIALIZATION_RECEIPT_MAX_BYTES = 4_194_304
_OPERATION_COMMITMENT_MAX_BYTES = 33_554_433
_SHA256_PATTERN = "^[0-9a-f]{64}$"


class TransformOutputAuthorityPersistenceState(StrEnum):
    """Read-only classification of the exact transform-output authority tables."""

    MIGRATION_REQUIRED = "migration-required"
    ALREADY_CURRENT = "already-current"
    REPAIR_REQUIRED = "repair-required"


class _TransformOutputAuthorityInstallTransactionState(StrEnum):
    NOT_STARTED = "not_started"
    BEGUN = "begun"
    COMMIT_ATTEMPTED = "commit_attempted"
    COMMITTED = "committed"


@dataclass(frozen=True, slots=True)
class TransformOutputAuthorityPersistenceClassification:
    """Stable classification without catalog OIDs, names, or raw DDL text."""

    state: TransformOutputAuthorityPersistenceState
    reason_code: str
    table_row_counts: tuple[tuple[str, int], ...] = ()


class TransformOutputAuthorityPersistenceError(RuntimeError):
    """The explicit authority-table installer could not prove a safe outcome."""

    def __init__(
        self,
        message: str,
        *,
        transaction_state: _TransformOutputAuthorityInstallTransactionState,
        classification: TransformOutputAuthorityPersistenceClassification | None = None,
    ) -> None:
        super().__init__(message)
        self.transaction_state = transaction_state
        self.classification = classification


@dataclass(frozen=True, slots=True)
class _ColumnSpec:
    name: str
    data_type: str
    nullable: bool = False
    default: str | None = None


@dataclass(frozen=True, slots=True)
class _CheckSpec:
    semantic_id: str
    columns: tuple[str, ...]
    expression: str


@dataclass(frozen=True, slots=True)
class _ConstraintSpec:
    kind: str
    columns: tuple[str, ...]
    referenced_table: str | None = None
    referenced_columns: tuple[str, ...] = ()
    check_semantic_id: str | None = None


@dataclass(frozen=True, slots=True)
class _TableSpec:
    name: str
    columns: tuple[_ColumnSpec, ...]
    primary_key: tuple[str, ...]
    unique_keys: tuple[tuple[str, ...], ...]
    foreign_keys: tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...]
    checks: tuple[_CheckSpec, ...]


def _sha_check(column: str) -> _CheckSpec:
    return _CheckSpec(
        semantic_id=f"{column}:lowercase_sha256",
        columns=(column,),
        expression=f"regexp_full_match({column}, '{_SHA256_PATTERN}')",
    )


def _codec_checks(*, prefix: str, maximum: int) -> tuple[_CheckSpec, ...]:
    return (
        _CheckSpec(
            semantic_id=f"{prefix}:canonical_byte_length_positive",
            columns=("canonical_byte_length",),
            expression="canonical_byte_length > 0",
        ),
        _CheckSpec(
            semantic_id=f"{prefix}:canonical_byte_length_maximum",
            columns=("canonical_byte_length",),
            expression=f"canonical_byte_length <= {maximum}",
        ),
        _CheckSpec(
            semantic_id=f"{prefix}:canonical_byte_length_projection",
            columns=("canonical_byte_length", "canonical_bytes"),
            expression="canonical_byte_length = octet_length(canonical_bytes)",
        ),
        _CheckSpec(
            semantic_id=f"{prefix}:canonical_bytes_sha256_projection",
            columns=("canonical_bytes_sha256", "canonical_bytes"),
            expression="canonical_bytes_sha256 = sha256(canonical_bytes)",
        ),
        _sha_check("canonical_bytes_sha256"),
    )


_AUTHORITY_TABLE_SPEC = _TableSpec(
    name=_TRANSFORM_OUTPUT_AUTHORITY_TABLE,
    columns=(
        _ColumnSpec("schema_version", "INTEGER"),
        _ColumnSpec("kind", "VARCHAR"),
        _ColumnSpec("generation_sequence", "BIGINT"),
        _ColumnSpec("prior_authority_envelope_sha256", "VARCHAR", nullable=True),
        _ColumnSpec("authority_envelope_sha256", "VARCHAR"),
        _ColumnSpec("disposition_generation_identity_sha256", "VARCHAR"),
        _ColumnSpec("authored_decision_authority_sha256", "VARCHAR"),
        _ColumnSpec("canonical_bytes", "BLOB"),
        _ColumnSpec("canonical_byte_length", "BIGINT"),
        _ColumnSpec("canonical_bytes_sha256", "VARCHAR"),
    ),
    primary_key=("authority_envelope_sha256",),
    unique_keys=(
        ("generation_sequence",),
        ("prior_authority_envelope_sha256",),
        ("authority_envelope_sha256", "disposition_generation_identity_sha256"),
    ),
    foreign_keys=(),
    checks=(
        _CheckSpec("authority:schema_version", ("schema_version",), "schema_version = 1"),
        _CheckSpec(
            "authority:kind",
            ("kind",),
            "kind = 'nbadb_verified_transform_output_disposition_authority_envelope'",
        ),
        _CheckSpec(
            "authority:generation_positive",
            ("generation_sequence",),
            "generation_sequence > 0",
        ),
        _CheckSpec(
            "authority:single_null_prior_root",
            ("generation_sequence", "prior_authority_envelope_sha256"),
            "(((generation_sequence = 1) AND "
            "(prior_authority_envelope_sha256 IS NULL)) OR "
            "((generation_sequence > 1) AND "
            "(prior_authority_envelope_sha256 IS NOT NULL)))",
        ),
        _sha_check("authority_envelope_sha256"),
        _sha_check("disposition_generation_identity_sha256"),
        _sha_check("authored_decision_authority_sha256"),
        _sha_check("prior_authority_envelope_sha256"),
        *_codec_checks(prefix="authority", maximum=_AUTHORITY_ENVELOPE_MAX_BYTES),
    ),
)

_RECEIPT_TABLE_SPEC = _TableSpec(
    name=_TRANSFORM_OUTPUT_RECEIPT_TABLE,
    columns=(
        _ColumnSpec("schema_version", "INTEGER"),
        _ColumnSpec("kind", "VARCHAR"),
        _ColumnSpec("receipt_sha256", "VARCHAR"),
        _ColumnSpec("original_materialization_id", "VARCHAR"),
        _ColumnSpec("transaction_generation_identity_sha256", "VARCHAR"),
        _ColumnSpec("output_name", "VARCHAR"),
        _ColumnSpec("disposition_entry_sha256", "VARCHAR"),
        _ColumnSpec("capability_policy_sha256", "VARCHAR"),
        _ColumnSpec("table_contract_sha256", "VARCHAR"),
        _ColumnSpec("schema_identity_sha256", "VARCHAR"),
        _ColumnSpec("transform_identity_sha256", "VARCHAR"),
        _ColumnSpec("ordered_columns_sha256", "VARCHAR"),
        _ColumnSpec("dependency_identity_sha256", "VARCHAR"),
        _ColumnSpec("materialization_scope", "VARCHAR"),
        _ColumnSpec("attestation_row_count", "BIGINT"),
        _ColumnSpec("attestation_schema_sha256", "VARCHAR"),
        _ColumnSpec("attestation_content_sha256", "VARCHAR"),
        _ColumnSpec("canonical_bytes", "BLOB"),
        _ColumnSpec("canonical_byte_length", "BIGINT"),
        _ColumnSpec("canonical_bytes_sha256", "VARCHAR"),
    ),
    primary_key=("receipt_sha256",),
    unique_keys=(("original_materialization_id",),),
    foreign_keys=(),
    checks=(
        _CheckSpec("receipt:schema_version", ("schema_version",), "schema_version = 1"),
        _CheckSpec(
            "receipt:kind",
            ("kind",),
            "kind = 'nbadb_transform_output_materialization_receipt'",
        ),
        _CheckSpec(
            "receipt:materialization_scope",
            ("materialization_scope",),
            "materialization_scope = 'primary_working_duckdb'",
        ),
        _CheckSpec(
            "receipt:original_materialization_id",
            ("original_materialization_id",),
            "regexp_full_match(original_materialization_id, "
            "'^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}$')",
        ),
        _CheckSpec(
            "receipt:output_name",
            ("output_name",),
            "regexp_full_match(output_name, "
            "'^(fact|dim|bridge|agg|analytics)_[a-z0-9]+(_[a-z0-9]+)*$')",
        ),
        _CheckSpec(
            "receipt:attestation_row_count",
            ("attestation_row_count",),
            "attestation_row_count >= 0",
        ),
        *(
            _sha_check(column)
            for column in (
                "receipt_sha256",
                "transaction_generation_identity_sha256",
                "disposition_entry_sha256",
                "capability_policy_sha256",
                "table_contract_sha256",
                "schema_identity_sha256",
                "transform_identity_sha256",
                "ordered_columns_sha256",
                "dependency_identity_sha256",
                "attestation_schema_sha256",
                "attestation_content_sha256",
            )
        ),
        *_codec_checks(prefix="receipt", maximum=_MATERIALIZATION_RECEIPT_MAX_BYTES),
    ),
)

_COMMITMENT_TABLE_SPEC = _TableSpec(
    name=_TRANSFORM_OUTPUT_COMMITMENT_TABLE,
    columns=(
        _ColumnSpec("schema_version", "INTEGER"),
        _ColumnSpec("kind", "VARCHAR"),
        _ColumnSpec("commitment_sha256", "VARCHAR"),
        _ColumnSpec("operation_identity_sha256", "VARCHAR"),
        _ColumnSpec("transaction_generation_identity_sha256", "VARCHAR"),
        _ColumnSpec("authority_envelope_sha256", "VARCHAR"),
        _ColumnSpec("disposition_generation_identity_sha256", "VARCHAR"),
        _ColumnSpec("authored_decision_authority_sha256", "VARCHAR"),
        _ColumnSpec("operation_data_evidence_sha256", "VARCHAR"),
        _ColumnSpec("binding_count", "BIGINT"),
        _ColumnSpec("binding_inventory_sha256", "VARCHAR"),
        _ColumnSpec("current_root_inventory_sha256", "VARCHAR"),
        _ColumnSpec("canonical_bytes", "BLOB"),
        _ColumnSpec("canonical_byte_length", "BIGINT"),
        _ColumnSpec("canonical_bytes_sha256", "VARCHAR"),
    ),
    primary_key=("commitment_sha256",),
    unique_keys=(
        ("operation_identity_sha256",),
        ("transaction_generation_identity_sha256",),
    ),
    foreign_keys=(
        (
            ("authority_envelope_sha256", "disposition_generation_identity_sha256"),
            _TRANSFORM_OUTPUT_AUTHORITY_TABLE,
            ("authority_envelope_sha256", "disposition_generation_identity_sha256"),
        ),
    ),
    checks=(
        _CheckSpec("commitment:schema_version", ("schema_version",), "schema_version = 1"),
        _CheckSpec(
            "commitment:kind",
            ("kind",),
            "kind = 'nbadb_transform_output_operation_commitment'",
        ),
        _CheckSpec("commitment:binding_count", ("binding_count",), "binding_count >= 0"),
        *(
            _sha_check(column)
            for column in (
                "commitment_sha256",
                "operation_identity_sha256",
                "transaction_generation_identity_sha256",
                "authority_envelope_sha256",
                "disposition_generation_identity_sha256",
                "authored_decision_authority_sha256",
                "operation_data_evidence_sha256",
                "binding_inventory_sha256",
                "current_root_inventory_sha256",
            )
        ),
        *_codec_checks(prefix="commitment", maximum=_OPERATION_COMMITMENT_MAX_BYTES),
    ),
)

_TRANSFORM_OUTPUT_AUTHORITY_TABLE_SPECS = (
    _AUTHORITY_TABLE_SPEC,
    _RECEIPT_TABLE_SPEC,
    _COMMITMENT_TABLE_SPEC,
)


def _table_ddl(spec: _TableSpec) -> str:
    definitions = [
        (
            f"{column.name} {column.data_type}"
            f"{'' if column.nullable else ' NOT NULL'}"
            f"{'' if column.default is None else f' DEFAULT {column.default}'}"
        )
        for column in spec.columns
    ]
    definitions.append(f"PRIMARY KEY ({', '.join(spec.primary_key)})")
    definitions.extend(f"UNIQUE ({', '.join(columns)})" for columns in spec.unique_keys)
    definitions.extend(
        f"FOREIGN KEY ({', '.join(columns)}) REFERENCES {referenced_table} "
        f"({', '.join(referenced_columns)})"
        for columns, referenced_table, referenced_columns in spec.foreign_keys
    )
    definitions.extend(f"CHECK ({check.expression})" for check in spec.checks)
    return f"CREATE TABLE {spec.name} (\n    " + ",\n    ".join(definitions) + "\n)"


_TRANSFORM_OUTPUT_AUTHORITY_DDL = tuple(
    (spec.name, _table_ddl(spec)) for spec in _TRANSFORM_OUTPUT_AUTHORITY_TABLE_SPECS
)


def _strip_enclosing_parentheses(value: str) -> str:
    while len(value) >= 2 and value[0] == "(" and value[-1] == ")":
        depth = 0
        in_literal = False
        enclosed = True
        index = 0
        while index < len(value):
            character = value[index]
            if in_literal:
                if character == "'":
                    if index + 1 < len(value) and value[index + 1] == "'":
                        index += 1
                    else:
                        in_literal = False
            elif character == "'":
                in_literal = True
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(value) - 1:
                    enclosed = False
                    break
            index += 1
        if not enclosed or depth != 0 or in_literal:
            break
        value = value[1:-1]
    return value


def _normalize_check_tokens(expression: object) -> str | None:
    if type(expression) is not str:
        return None
    tokens: list[str] = []
    in_literal = False
    index = 0
    while index < len(expression):
        character = expression[index]
        if in_literal:
            tokens.append(character)
            if character == "'":
                if index + 1 < len(expression) and expression[index + 1] == "'":
                    tokens.append("'")
                    index += 1
                else:
                    in_literal = False
        elif character == "'":
            in_literal = True
            tokens.append(character)
        elif not character.isspace():
            tokens.append(character.lower())
        index += 1
    if in_literal:
        return None
    return _strip_enclosing_parentheses("".join(tokens))


def _constraint_sort_key(spec: _ConstraintSpec) -> tuple[object, ...]:
    return (
        spec.kind,
        spec.columns,
        spec.referenced_table or "",
        spec.referenced_columns,
        spec.check_semantic_id or "",
    )


def _expected_constraints(spec: _TableSpec) -> tuple[_ConstraintSpec, ...]:
    constraints = [
        _ConstraintSpec("NOT NULL", (column.name,))
        for column in spec.columns
        if not column.nullable
    ]
    constraints.append(_ConstraintSpec("PRIMARY KEY", spec.primary_key))
    constraints.extend(_ConstraintSpec("UNIQUE", columns) for columns in spec.unique_keys)
    constraints.extend(
        _ConstraintSpec(
            "FOREIGN KEY",
            columns,
            referenced_table=referenced_table,
            referenced_columns=referenced_columns,
        )
        for columns, referenced_table, referenced_columns in spec.foreign_keys
    )
    constraints.extend(
        _ConstraintSpec(
            "CHECK",
            check.columns,
            check_semantic_id=check.semantic_id,
        )
        for check in spec.checks
    )
    return tuple(sorted(constraints, key=_constraint_sort_key))


def _observed_columns(
    connection: duckdb.DuckDBPyConnection,
    *,
    database_name: str,
    table_name: str,
) -> tuple[_ColumnSpec, ...]:
    rows = connection.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM duckdb_columns()
        WHERE database_name = $1 AND schema_name = 'main' AND table_name = $2
        ORDER BY column_index
        """,
        [database_name, table_name],
    ).fetchall()
    return tuple(
        _ColumnSpec(
            name=str(column_name),
            data_type=str(data_type).upper(),
            nullable=bool(is_nullable),
            default=None if column_default is None else str(column_default),
        )
        for column_name, data_type, is_nullable, column_default in rows
    )


def _observed_constraints(
    connection: duckdb.DuckDBPyConnection,
    *,
    database_name: str,
    spec: _TableSpec,
) -> tuple[_ConstraintSpec, ...]:
    rows = connection.execute(
        """
        SELECT constraint_type,
               constraint_column_names,
               referenced_table,
               referenced_column_names,
               expression
        FROM duckdb_constraints()
        WHERE database_name = $1 AND schema_name = 'main' AND table_name = $2
        """,
        [database_name, spec.name],
    ).fetchall()
    check_semantics = {
        _normalize_check_tokens(check.expression): check.semantic_id for check in spec.checks
    }
    constraints = []
    for kind, columns, referenced_table, referenced_columns, expression in rows:
        normalized_kind = str(kind).upper()
        raw_columns = tuple(str(column) for column in (columns or []))
        normalized_columns = (
            tuple(dict.fromkeys(raw_columns)) if normalized_kind == "CHECK" else raw_columns
        )
        semantic_id = None
        if normalized_kind == "CHECK":
            semantic_id = check_semantics.get(_normalize_check_tokens(expression))
            if semantic_id is None:
                semantic_id = "unrecognized-check-semantics"
        constraints.append(
            _ConstraintSpec(
                kind=normalized_kind,
                columns=normalized_columns,
                referenced_table=(None if referenced_table is None else str(referenced_table)),
                referenced_columns=tuple(str(column) for column in (referenced_columns or [])),
                check_semantic_id=semantic_id,
            )
        )
    return tuple(sorted(constraints, key=_constraint_sort_key))


def _catalog_classification(
    connection: duckdb.DuckDBPyConnection,
) -> TransformOutputAuthorityPersistenceClassification:
    database_row = connection.execute("SELECT current_database()").fetchone()
    if database_row is None or type(database_row[0]) is not str:
        return TransformOutputAuthorityPersistenceClassification(
            TransformOutputAuthorityPersistenceState.REPAIR_REQUIRED,
            "database_identity_unavailable",
        )
    database_name = database_row[0]
    expected_names = frozenset(_TRANSFORM_OUTPUT_AUTHORITY_TABLES)
    expected_name_keys = frozenset(name.lower() for name in expected_names)
    table_rows = connection.execute(
        """
        SELECT database_name, schema_name, table_name, temporary
        FROM duckdb_tables()
        WHERE schema_name = 'main'
        """
    ).fetchall()
    view_rows = connection.execute(
        """
        SELECT database_name, schema_name, view_name, temporary
        FROM duckdb_views()
        WHERE schema_name = 'main'
        """
    ).fetchall()
    conflicting = {
        str(name)
        for observed_database, _schema, name, temporary in (*table_rows, *view_rows)
        if str(name).lower() in expected_name_keys
        and (bool(temporary) or str(observed_database) == database_name)
        and (
            bool(temporary)
            or any(
                str(view_name).lower() == str(name).lower()
                and str(view_database) == str(observed_database)
                and bool(view_temporary) == bool(temporary)
                for view_database, _view_schema, view_name, view_temporary in view_rows
            )
        )
    }
    if conflicting:
        return TransformOutputAuthorityPersistenceClassification(
            TransformOutputAuthorityPersistenceState.REPAIR_REQUIRED,
            "view_or_temporary_conflict",
        )
    persistent_name_keys = {
        str(table_name).lower()
        for observed_database, _schema, table_name, temporary in table_rows
        if not bool(temporary)
        and str(observed_database) == database_name
        and str(table_name).lower() in expected_name_keys
    }
    if not persistent_name_keys:
        return TransformOutputAuthorityPersistenceClassification(
            TransformOutputAuthorityPersistenceState.MIGRATION_REQUIRED,
            "all_absent",
        )
    if persistent_name_keys != expected_name_keys:
        return TransformOutputAuthorityPersistenceClassification(
            TransformOutputAuthorityPersistenceState.REPAIR_REQUIRED,
            "partial_table_set",
        )
    for spec in _TRANSFORM_OUTPUT_AUTHORITY_TABLE_SPECS:
        if (
            _observed_columns(
                connection,
                database_name=database_name,
                table_name=spec.name,
            )
            != spec.columns
        ):
            return TransformOutputAuthorityPersistenceClassification(
                TransformOutputAuthorityPersistenceState.REPAIR_REQUIRED,
                "column_shape_mismatch",
            )
        if _observed_constraints(
            connection,
            database_name=database_name,
            spec=spec,
        ) != _expected_constraints(spec):
            return TransformOutputAuthorityPersistenceClassification(
                TransformOutputAuthorityPersistenceState.REPAIR_REQUIRED,
                "constraint_shape_mismatch",
            )
    return TransformOutputAuthorityPersistenceClassification(
        TransformOutputAuthorityPersistenceState.ALREADY_CURRENT,
        "all_exact",
    )


def _read_transform_output_authority_row_counts(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[tuple[str, int], ...]:
    counts = []
    for table_name in _TRANSFORM_OUTPUT_AUTHORITY_TABLES:
        row = connection.execute(f'SELECT COUNT(*) FROM main."{table_name}"').fetchone()
        if row is None or type(row[0]) is not int:
            raise RuntimeError(f"row count unavailable for exact table {table_name}")
        counts.append((table_name, row[0]))
    return tuple(counts)


def classify_transform_output_authority_persistence(
    connection: duckdb.DuckDBPyConnection,
) -> TransformOutputAuthorityPersistenceClassification:
    """Classify the three strict tables without creating, repairing, or rewriting them."""

    classification = _catalog_classification(connection)
    if classification.state is not TransformOutputAuthorityPersistenceState.ALREADY_CURRENT:
        return classification
    return TransformOutputAuthorityPersistenceClassification(
        classification.state,
        classification.reason_code,
        _read_transform_output_authority_row_counts(connection),
    )


class DuckDBLockError(RuntimeError):
    """Raised when the writable DuckDB file is locked by another process."""


def _is_duckdb_lock_error(exc: duckdb.IOException) -> bool:
    return _DUCKDB_LOCK_ERROR_FRAGMENT in str(exc)


def _format_duckdb_lock_error(path: Path, exc: duckdb.IOException) -> str:
    return (
        f"DuckDB database is locked at {path}. "
        "Close other nbadb or DuckDB processes using this file, "
        "or use a different data directory. "
        f"Original error: {exc}"
    )


class DBManager:
    def __init__(
        self,
        sqlite_path: Path | None = None,
        duckdb_path: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._sqlite_path = sqlite_path or settings.sqlite_path
        self._duckdb_path = duckdb_path or settings.duckdb_path
        self._engine: Engine | None = None
        self._duckdb_conn: _duckdb_type.DuckDBPyConnection | None = None

    def init(self) -> None:
        if self._sqlite_path is None:
            raise ValueError("sqlite_path required")
        if self._duckdb_path is None:
            raise ValueError("duckdb_path required")
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._duckdb_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{self._sqlite_path}", echo=False)
        self._apply_sqlite_pragmas()
        SQLModel.metadata.create_all(self._engine)
        self._duckdb_conn = self._connect_duckdb()
        self._duckdb_conn.execute("SET preserve_insertion_order = false")
        self._create_pipeline_tables()
        logger.info(f"DB initialized: SQLite={self._sqlite_path}, DuckDB={self._duckdb_path}")

    def _connect_duckdb(self) -> _duckdb_type.DuckDBPyConnection:
        if self._duckdb_path is None:
            raise ValueError("duckdb_path required")

        last_lock_error: duckdb.IOException | None = None
        for attempt in range(1, _DUCKDB_LOCK_RETRY_ATTEMPTS + 1):
            try:
                return duckdb.connect(str(self._duckdb_path))
            except duckdb.IOException as exc:
                if not _is_duckdb_lock_error(exc):
                    raise
                last_lock_error = exc
                if attempt == _DUCKDB_LOCK_RETRY_ATTEMPTS:
                    break
                delay_seconds = _DUCKDB_LOCK_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "duckdb lock conflict on {} (attempt {}/{}), retrying in {:.1f}s",
                    self._duckdb_path,
                    attempt,
                    _DUCKDB_LOCK_RETRY_ATTEMPTS,
                    delay_seconds,
                )
                time.sleep(delay_seconds)

        if last_lock_error is None:
            raise RuntimeError("duckdb connection failed without a captured lock error")
        raise DuckDBLockError(
            _format_duckdb_lock_error(self._duckdb_path, last_lock_error)
        ) from last_lock_error

    def _apply_sqlite_pragmas(self) -> None:
        if self._engine is None:
            raise RuntimeError("DB not initialized")
        with self._engine.connect() as conn:
            for pragma in [
                "PRAGMA journal_mode = WAL",
                "PRAGMA synchronous = NORMAL",
                "PRAGMA cache_size = -262144",
                "PRAGMA page_size = 16384",  # only effective on newly created databases
                "PRAGMA mmap_size = 1073741824",
                "PRAGMA temp_store = MEMORY",
            ]:
                conn.execute(text(pragma))
            conn.commit()

    def _create_pipeline_tables(self) -> None:
        if self._duckdb_conn is None:
            raise RuntimeError("DB not initialized")
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _pipeline_watermarks (
                table_name VARCHAR NOT NULL,
                watermark_type VARCHAR NOT NULL,
                watermark_value VARCHAR,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                row_count_at_watermark BIGINT,
                PRIMARY KEY (table_name, watermark_type)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _extraction_journal (
                endpoint VARCHAR NOT NULL,
                params VARCHAR,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0,
                PRIMARY KEY (endpoint, params)
            )
        """)
        # Migrate existing DBs that lack retry_count
        self._duckdb_conn.execute("""
            ALTER TABLE _extraction_journal
            ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0
        """)
        for column, data_type in (
            ("logical_call_receipt_sha256", "VARCHAR"),
            ("provider_authority_sha256", "VARCHAR"),
            ("logical_parameters_sha256", "VARCHAR"),
            ("result_route_ids_json", "VARCHAR"),
            ("w2_required", "BOOLEAN DEFAULT FALSE"),
            ("w2_source_call_admission_sha256", "VARCHAR"),
            ("w2_source_call_admission_bytes", "BLOB"),
            ("raw_authority_bundle_sha256", "VARCHAR"),
            ("raw_authority_persistence_receipt_sha256", "VARCHAR"),
            ("committed_staging_readback_count", "BIGINT"),
            ("committed_staging_readback_root_sha256", "VARCHAR"),
            ("w2_operation_key_sha256", "VARCHAR"),
            ("w2_operation_receipt_sha256", "VARCHAR"),
            ("w2_operation_persistence_receipt_sha256", "VARCHAR"),
        ):
            self._duckdb_conn.execute(
                f"ALTER TABLE _extraction_journal ADD COLUMN IF NOT EXISTS {column} {data_type}"
            )
        self._duckdb_conn.execute(
            "UPDATE _extraction_journal SET w2_required = FALSE WHERE w2_required IS NULL"
        )
        self._duckdb_conn.execute(
            "ALTER TABLE _extraction_journal ALTER COLUMN w2_required SET NOT NULL"
        )
        # Seed existing failed entries: assume they've been tried ~4 times already
        # so they get one more attempt before being abandoned at MAX_RETRIES=5.
        self._duckdb_conn.execute("""
            UPDATE _extraction_journal
            SET retry_count = 4
            WHERE status = 'failed' AND retry_count = 0
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _pipeline_metadata (
                table_name VARCHAR PRIMARY KEY,
                last_updated TIMESTAMP,
                row_count BIGINT,
                schema_hash VARCHAR
            )
        """)
        self._duckdb_conn.execute("""
            ALTER TABLE _pipeline_metadata
            ADD COLUMN IF NOT EXISTS quality_score DOUBLE
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _pipeline_metrics (
                endpoint VARCHAR NOT NULL,
                run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                duration_seconds FLOAT,
                rows_extracted BIGINT,
                error_count INT DEFAULT 0,
                PRIMARY KEY (endpoint, run_timestamp)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _transform_checkpoints (
                run_id VARCHAR NOT NULL,
                table_name VARCHAR NOT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                row_count BIGINT,
                PRIMARY KEY (run_id, table_name)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_versions (
                table_name VARCHAR NOT NULL,
                version INT NOT NULL DEFAULT 1,
                column_hash VARCHAR NOT NULL,
                columns_json VARCHAR NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (table_name)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_version_history (
                table_name VARCHAR NOT NULL,
                version INT NOT NULL,
                column_hash VARCHAR NOT NULL,
                columns_json VARCHAR NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (table_name, version)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _transform_metrics (
                run_id VARCHAR NOT NULL,
                table_name VARCHAR NOT NULL,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                duration_seconds FLOAT,
                row_count BIGINT,
                column_count INT,
                status VARCHAR NOT NULL DEFAULT 'success',
                error_message VARCHAR,
                PRIMARY KEY (run_id, table_name)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _lane_metrics (
                lane_id VARCHAR NOT NULL,
                run_mode VARCHAR NOT NULL,
                pattern VARCHAR NOT NULL,
                endpoint_families VARCHAR,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                wall_time_seconds FLOAT,
                task_count BIGINT,
                row_count BIGINT,
                success_count BIGINT,
                failure_count BIGINT,
                retry_inflation FLOAT DEFAULT 0,
                queue_wait_seconds FLOAT DEFAULT 0,
                PRIMARY KEY (lane_id)
            )
        """)
        self._duckdb_conn.execute("""
            CREATE TABLE IF NOT EXISTS _staging_chunk_journal (
                chunk_id VARCHAR NOT NULL,
                staging_key VARCHAR NOT NULL,
                row_count BIGINT NOT NULL,
                content_hash VARCHAR NOT NULL,
                source_label VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chunk_id, staging_key)
            )
        """)
        for column, data_type in (
            ("persisted_row_count", "BIGINT"),
            ("persisted_content_sha256", "VARCHAR"),
            ("persisted_schema_sha256", "VARCHAR"),
            ("logical_call_receipt_sha256", "VARCHAR"),
            ("provider_authority_sha256", "VARCHAR"),
            ("logical_parameters_sha256", "VARCHAR"),
            ("result_route_id", "VARCHAR"),
        ):
            self._duckdb_conn.execute(
                f"ALTER TABLE _staging_chunk_journal ADD COLUMN IF NOT EXISTS {column} {data_type}"
            )

    def classify_transform_output_authority_persistence(
        self,
    ) -> TransformOutputAuthorityPersistenceClassification:
        """Read the strict-table state without installing or repairing it."""

        return classify_transform_output_authority_persistence(self.duckdb)

    def install_transform_output_authority_persistence(
        self,
    ) -> TransformOutputAuthorityPersistenceClassification:
        """Install the exact three-table schema only from the all-absent state."""

        return _install_transform_output_authority_persistence(self)

    @property
    def engine(self) -> Engine:
        if not self._engine:
            raise RuntimeError("DB not initialized. Call init() first.")
        return self._engine

    @property
    def duckdb(self) -> duckdb.DuckDBPyConnection:  # ty: ignore[unresolved-attribute]
        if not self._duckdb_conn:
            raise RuntimeError("DB not initialized. Call init() first.")
        return self._duckdb_conn

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        with Session(self.engine) as session:
            yield session

    def close(self) -> None:
        if self._engine:
            self._engine.dispose()
        if self._duckdb_conn:
            self._duckdb_conn.close()
        logger.info("DB connections closed")

    def __enter__(self) -> DBManager:
        self.init()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _connection_has_explicit_transaction(
    connection: duckdb.DuckDBPyConnection,
) -> bool:
    """Observe explicit transaction continuity without issuing a nested BEGIN."""

    first = connection.execute("SELECT current_transaction_id()").fetchone()
    second = connection.execute("SELECT current_transaction_id()").fetchone()
    if first is None or second is None or type(first[0]) is not int or type(second[0]) is not int:
        raise TransformOutputAuthorityPersistenceError(
            "DuckDB transaction identity is unavailable",
            transaction_state=_TransformOutputAuthorityInstallTransactionState.NOT_STARTED,
        )
    return first[0] == second[0]


def _prove_connection_transaction_usable(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    if _connection_has_explicit_transaction(connection):
        raise RuntimeError("connection retained an unexpected explicit transaction")
    connection.execute("BEGIN TRANSACTION")
    connection.execute("ROLLBACK")
    if _connection_has_explicit_transaction(connection):
        raise RuntimeError("connection transaction probe did not close")


def _inject_install_fault(
    fault_injector: Callable[[str], None] | None,
    event: str,
) -> None:
    if fault_injector is not None:
        fault_injector(event)


def _commit_transform_output_authority_install(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    connection.execute("COMMIT")


def _reopen_after_uncertain_authority_install(
    manager: DBManager,
    original_connection: duckdb.DuckDBPyConnection,
) -> TransformOutputAuthorityPersistenceClassification:
    if manager._duckdb_path is None or str(manager._duckdb_path) == ":memory:":
        manager._duckdb_conn = None
        original_connection.close()
        raise TransformOutputAuthorityPersistenceError(
            "commit-uncertain recovery requires a file-backed DuckDB database",
            transaction_state=_TransformOutputAuthorityInstallTransactionState.COMMIT_ATTEMPTED,
        )
    manager._duckdb_conn = None
    try:
        original_connection.close()
    finally:
        replacement = manager._connect_duckdb()
        replacement.execute("SET preserve_insertion_order = false")
        manager._duckdb_conn = replacement
    return classify_transform_output_authority_persistence(manager.duckdb)


def _raise_precommit_install_failure(
    *,
    connection: duckdb.DuckDBPyConnection,
    cause: BaseException,
) -> None:
    try:
        connection.execute("ROLLBACK")
        classification = classify_transform_output_authority_persistence(connection)
        if classification.state is TransformOutputAuthorityPersistenceState.MIGRATION_REQUIRED:
            _prove_connection_transaction_usable(connection)
        elif classification.state is TransformOutputAuthorityPersistenceState.ALREADY_CURRENT:
            raise TransformOutputAuthorityPersistenceError(
                "another installer committed while the owned transaction failed",
                transaction_state=_TransformOutputAuthorityInstallTransactionState.BEGUN,
                classification=classification,
            ) from cause
        else:
            raise TransformOutputAuthorityPersistenceError(
                "pre-commit rollback exposed repair-required authority persistence state",
                transaction_state=_TransformOutputAuthorityInstallTransactionState.BEGUN,
                classification=classification,
            ) from cause
    except TransformOutputAuthorityPersistenceError:
        raise
    except BaseException as rollback_error:
        raise TransformOutputAuthorityPersistenceError(
            "owned authority installer transaction could not be rolled back and revalidated",
            transaction_state=_TransformOutputAuthorityInstallTransactionState.BEGUN,
        ) from rollback_error
    raise TransformOutputAuthorityPersistenceError(
        "owned authority installer transaction failed and was rolled back",
        transaction_state=_TransformOutputAuthorityInstallTransactionState.BEGUN,
        classification=classification,
    ) from cause


def _install_transform_output_authority_persistence(
    manager: DBManager,
    *,
    fault_injector: Callable[[str], None] | None = None,
) -> TransformOutputAuthorityPersistenceClassification:
    with _TRANSFORM_OUTPUT_AUTHORITY_INSTALL_LOCK:
        connection = manager.duckdb
        transaction_state = _TransformOutputAuthorityInstallTransactionState.NOT_STARTED
        if _connection_has_explicit_transaction(connection):
            raise TransformOutputAuthorityPersistenceError(
                "authority installer refuses a caller-owned DuckDB transaction",
                transaction_state=transaction_state,
            )
        try:
            connection.execute("BEGIN TRANSACTION")
        except BaseException as exc:
            raise TransformOutputAuthorityPersistenceError(
                "authority installer could not begin its owned transaction",
                transaction_state=transaction_state,
            ) from exc
        transaction_state = _TransformOutputAuthorityInstallTransactionState.BEGUN

        try:
            initial = _catalog_classification(connection)
            if initial.state is not TransformOutputAuthorityPersistenceState.MIGRATION_REQUIRED:
                connection.execute("ROLLBACK")
                transaction_state = _TransformOutputAuthorityInstallTransactionState.NOT_STARTED
                return classify_transform_output_authority_persistence(connection)

            event_names = (
                "after_create_authority",
                "after_create_receipts",
                "after_create_commitments",
            )
            for (_table_name, ddl), event_name in zip(
                _TRANSFORM_OUTPUT_AUTHORITY_DDL,
                event_names,
                strict=True,
            ):
                connection.execute(ddl)
                _inject_install_fault(fault_injector, event_name)

            catalog = _catalog_classification(connection)
            if catalog.state is not TransformOutputAuthorityPersistenceState.ALREADY_CURRENT:
                raise RuntimeError("created authority tables differ from the exact catalog")
            _inject_install_fault(fault_injector, "after_catalog_validation")

            row_counts = _read_transform_output_authority_row_counts(connection)
            if any(row_count != 0 for _table_name, row_count in row_counts):
                raise RuntimeError("new authority tables did not read back exact-empty")
            _inject_install_fault(fault_injector, "after_empty_readback")
            _inject_install_fault(fault_injector, "before_commit")
        except BaseException as exc:
            _raise_precommit_install_failure(connection=connection, cause=exc)

        transaction_state = _TransformOutputAuthorityInstallTransactionState.COMMIT_ATTEMPTED
        try:
            _commit_transform_output_authority_install(connection)
        except BaseException as exc:
            classification = _reopen_after_uncertain_authority_install(manager, connection)
            if classification.state is TransformOutputAuthorityPersistenceState.ALREADY_CURRENT:
                return classification
            raise TransformOutputAuthorityPersistenceError(
                "authority installer commit was uncertain and did not prove exact installation",
                transaction_state=transaction_state,
                classification=classification,
            ) from exc

        transaction_state = _TransformOutputAuthorityInstallTransactionState.COMMITTED
        try:
            _inject_install_fault(fault_injector, "after_commit")
            classification = classify_transform_output_authority_persistence(connection)
        except BaseException as exc:
            classification = classify_transform_output_authority_persistence(connection)
            raise TransformOutputAuthorityPersistenceError(
                "authority installation committed but post-commit validation failed",
                transaction_state=transaction_state,
                classification=classification,
            ) from exc
        if classification.state is not TransformOutputAuthorityPersistenceState.ALREADY_CURRENT:
            raise TransformOutputAuthorityPersistenceError(
                "authority installation committed into a non-current state",
                transaction_state=transaction_state,
                classification=classification,
            )
        return classification


def get_user_tables(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Return sorted list of user-created table names in the main schema.

    Excludes internal pipeline tables (prefixed with underscore).
    """
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' "
        "AND table_name NOT LIKE '\\_%' ESCAPE '\\'"
    ).fetchall()
    return sorted(row[0] for row in rows)
