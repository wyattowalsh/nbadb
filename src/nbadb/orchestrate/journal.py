from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.extract.bronze import LogicalCallReceiptBinding, canonical_parameters_sha256
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    SourceScopeReplacementAttestation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import duckdb

    from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SUCCESSOR_JOURNAL_TABLE = "_successor_extraction_journal"
_RECEIPT_COLUMNS = (
    "logical_call_receipt_sha256",
    "provider_authority_sha256",
    "logical_parameters_sha256",
    "result_route_ids_json",
)
_W2_JOURNAL_COLUMNS = (
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
)
_AUTHORITY_COLUMNS = (*_RECEIPT_COLUMNS, *(name for name, _ in _W2_JOURNAL_COLUMNS))
_W2_EVIDENCE_COLUMNS = tuple(name for name, _ in _W2_JOURNAL_COLUMNS[1:])
_AUTHORITY_SQL_TYPES = {
    "logical_call_receipt_sha256": "VARCHAR",
    "provider_authority_sha256": "VARCHAR",
    "logical_parameters_sha256": "VARCHAR",
    "result_route_ids_json": "VARCHAR",
    "w2_required": "BOOLEAN",
    "w2_source_call_admission_sha256": "VARCHAR",
    "w2_source_call_admission_bytes": "BLOB",
    "raw_authority_bundle_sha256": "VARCHAR",
    "raw_authority_persistence_receipt_sha256": "VARCHAR",
    "committed_staging_readback_count": "BIGINT",
    "committed_staging_readback_root_sha256": "VARCHAR",
    "w2_operation_key_sha256": "VARCHAR",
    "w2_operation_receipt_sha256": "VARCHAR",
    "w2_operation_persistence_receipt_sha256": "VARCHAR",
}


@dataclass(frozen=True, slots=True)
class _JournalAuthorityRow:
    logical_call_receipt_sha256: object
    provider_authority_sha256: object
    logical_parameters_sha256: object
    result_route_ids_json: object
    w2_required: object
    w2_source_call_admission_sha256: object
    w2_source_call_admission_bytes: object
    raw_authority_bundle_sha256: object
    raw_authority_persistence_receipt_sha256: object
    committed_staging_readback_count: object
    committed_staging_readback_root_sha256: object
    w2_operation_key_sha256: object
    w2_operation_receipt_sha256: object
    w2_operation_persistence_receipt_sha256: object

    @classmethod
    def from_row(cls, row: object) -> _JournalAuthorityRow | None:
        if type(row) is not tuple or len(row) != len(_AUTHORITY_COLUMNS):
            return None
        return cls(**dict(zip(_AUTHORITY_COLUMNS, row, strict=True)))

    def receipt_row(self) -> tuple[object, ...]:
        return tuple(getattr(self, name) for name in _RECEIPT_COLUMNS)

    def w2_evidence_is_clear(self) -> bool:
        return all(getattr(self, name) is None for name in _W2_EVIDENCE_COLUMNS)


def _uses_v2_frame_contracts(
    canonical_frame_format: object,
    frame_content_hash_contract: object,
    frame_schema_hash_contract: object,
) -> bool:
    return (
        type(canonical_frame_format) is str
        and canonical_frame_format == CANONICAL_FRAME_FORMAT
        and type(frame_content_hash_contract) is str
        and frame_content_hash_contract == FRAME_CONTENT_HASH_CONTRACT
        and type(frame_schema_hash_contract) is str
        and frame_schema_hash_contract == FRAME_SCHEMA_HASH_CONTRACT
    )


def _system_utc_now() -> datetime:
    return datetime.now(UTC)


class PipelineJournal:
    """Thin wrapper around the DuckDB pipeline tables.

    Tables are created by ``DBManager._create_pipeline_tables()``.
    Writable callers migrate additive receipt columns by default. Read-only
    inspection callers must opt out with ``migrate_schema=False``.
    """

    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        migrate_schema: bool = True,
        successor_generation_sha256: str | None = None,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        if successor_generation_sha256 is not None and (
            not isinstance(successor_generation_sha256, str)
            or _SHA256_RE.fullmatch(successor_generation_sha256) is None
        ):
            raise ValueError("successor_generation_sha256 must be a lowercase SHA-256")
        self._conn = conn
        self._successor_generation_sha256 = successor_generation_sha256
        self._utc_now = utc_now or _system_utc_now
        if migrate_schema:
            if successor_generation_sha256 is None:
                self._ensure_receipt_schema()
            else:
                self._ensure_successor_schema()

    @property
    def successor_generation_sha256(self) -> str | None:
        return self._successor_generation_sha256

    @property
    def _extraction_table(self) -> str:
        return (
            _SUCCESSOR_JOURNAL_TABLE
            if self._successor_generation_sha256 is not None
            else "_extraction_journal"
        )

    def _authority_projection(self) -> str:
        """Return a shape-stable, read-only authority projection for this table.

        Deliberately unmigrated legacy journals have none of the receipt/W2
        columns.  Read/report callers retain their documented non-W2 behavior
        by projecting missing evidence as NULL and the absent W2 marker as
        FALSE.  A present marker is always read verbatim, so TRUE, NULL, or a
        foreign type can never be downgraded into legacy authority.
        """

        rows = self._conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = $1
            """,
            [self._extraction_table],
        ).fetchall()
        if any(type(row) is not tuple or len(row) != 1 or type(row[0]) is not str for row in rows):
            raise RuntimeError("journal column inventory is malformed")
        available = {row[0] for row in rows}
        if tuple(_AUTHORITY_SQL_TYPES) != _AUTHORITY_COLUMNS:
            raise RuntimeError("journal authority SQL type map is inconsistent")
        projection = tuple(
            name
            if name in available
            else f"CAST(FALSE AS BOOLEAN) AS {name}"
            if name == "w2_required"
            else f"CAST(NULL AS {_AUTHORITY_SQL_TYPES[name]}) AS {name}"
            for name in _AUTHORITY_COLUMNS
        )
        return ",\n                       ".join(projection)

    def _ensure_receipt_schema(self) -> None:
        for column, data_type in (
            *((name, "VARCHAR") for name in _RECEIPT_COLUMNS),
            *_W2_JOURNAL_COLUMNS,
        ):
            self._conn.execute(
                f"ALTER TABLE _extraction_journal ADD COLUMN IF NOT EXISTS {column} {data_type}"
            )
        self._conn.execute(
            "UPDATE _extraction_journal SET w2_required = FALSE WHERE w2_required IS NULL"
        )
        self._conn.execute("ALTER TABLE _extraction_journal ALTER COLUMN w2_required SET NOT NULL")

    def _ensure_successor_schema(self) -> None:
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_SUCCESSOR_JOURNAL_TABLE} (
                successor_generation_sha256 VARCHAR NOT NULL,
                endpoint VARCHAR NOT NULL,
                params VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0,
                logical_call_receipt_sha256 VARCHAR,
                provider_authority_sha256 VARCHAR,
                logical_parameters_sha256 VARCHAR,
                result_route_ids_json VARCHAR,
                w2_required BOOLEAN NOT NULL DEFAULT FALSE,
                w2_source_call_admission_sha256 VARCHAR,
                w2_source_call_admission_bytes BLOB,
                raw_authority_bundle_sha256 VARCHAR,
                raw_authority_persistence_receipt_sha256 VARCHAR,
                committed_staging_readback_count BIGINT,
                committed_staging_readback_root_sha256 VARCHAR,
                w2_operation_key_sha256 VARCHAR,
                w2_operation_receipt_sha256 VARCHAR,
                w2_operation_persistence_receipt_sha256 VARCHAR,
                PRIMARY KEY (successor_generation_sha256, endpoint, params)
            )
            """
        )
        for column, data_type in _W2_JOURNAL_COLUMNS:
            self._conn.execute(
                f"ALTER TABLE {_SUCCESSOR_JOURNAL_TABLE} "
                f"ADD COLUMN IF NOT EXISTS {column} {data_type}"
            )
        self._conn.execute(
            f"UPDATE {_SUCCESSOR_JOURNAL_TABLE} SET w2_required = FALSE WHERE w2_required IS NULL"
        )
        self._conn.execute(
            f"ALTER TABLE {_SUCCESSOR_JOURNAL_TABLE} ALTER COLUMN w2_required SET NOT NULL"
        )

    def _require_baseline_extraction_journal(self, operation: str) -> None:
        if self._successor_generation_sha256 is not None:
            raise RuntimeError(
                f"{operation} is unavailable when successor_generation_sha256 is set"
            )

    def _now_iso(self) -> str:
        value = self._utc_now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("utc_now must return an aware datetime")
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _require_w2_flag(value: object) -> bool:
        if type(value) is not bool:
            raise TypeError("require_w2_operation must be an exact boolean")
        return value

    @staticmethod
    def _authority_from_row(row: object) -> _JournalAuthorityRow | None:
        return _JournalAuthorityRow.from_row(row)

    def _verified_w2_admission(
        self,
        authority: _JournalAuthorityRow,
        binding: LogicalCallReceiptBinding,
    ) -> W2SourceCallAdmissionV1 | None:
        from nbadb.orchestrate.w2_operation_coordinator import (
            W2SourceCallAdmissionV1,
            verify_w2_source_call_admission,
        )
        from nbadb.orchestrate.w2_operation_store import W2OperationStore

        if (
            authority.w2_required is not True
            or type(authority.w2_source_call_admission_bytes) is not bytes
            or not authority.w2_source_call_admission_bytes
        ):
            return None
        try:
            admission = W2SourceCallAdmissionV1.from_canonical_bytes(
                authority.w2_source_call_admission_bytes
            )
            verified = verify_w2_source_call_admission(
                admission,
                expected_admission_sha256=(authority.w2_source_call_admission_sha256),
                expected_logical_call_receipt_sha256=(binding.logical_call_receipt_sha256),
                expected_raw_authority_bundle_sha256=(authority.raw_authority_bundle_sha256),
                expected_raw_authority_persistence_receipt_sha256=(
                    authority.raw_authority_persistence_receipt_sha256
                ),
                expected_committed_staging_readback_count=(
                    authority.committed_staging_readback_count
                ),
                expected_committed_staging_readback_root_sha256=(
                    authority.committed_staging_readback_root_sha256
                ),
                expected_operation_key_sha256=authority.w2_operation_key_sha256,
                expected_operation_receipt_sha256=(authority.w2_operation_receipt_sha256),
                expected_w2_operation_persistence_receipt_sha256=(
                    authority.w2_operation_persistence_receipt_sha256
                ),
                operation_store=W2OperationStore(self._conn),
            )
        except Exception:
            return None
        if verified.logical_call_receipt_sha256 != binding.logical_call_receipt_sha256:
            return None
        return verified

    def _done_authority_matches(
        self,
        endpoint: object,
        params: object,
        authority: _JournalAuthorityRow | None,
        *,
        require_receipt: bool,
        require_w2_operation: bool,
    ) -> bool:
        if authority is None or type(authority.w2_required) is not bool:
            return False
        if require_w2_operation and not authority.w2_required:
            return False
        if not authority.w2_required and not authority.w2_evidence_is_clear():
            return False
        receipt_required = require_receipt or require_w2_operation or authority.w2_required
        if not receipt_required:
            return True
        binding = self._receipt_binding_from_row(authority.receipt_row())
        if (
            binding is None
            or not self._receipt_binding_matches_endpoint(binding, endpoint)
            or not self._receipt_binding_matches_params(binding, params)
            or not self._staging_receipt_binding_matches(binding)
        ):
            return False
        if not authority.w2_required:
            return not require_w2_operation
        return self._verified_w2_admission(authority, binding) is not None

    def _effective_status(
        self,
        endpoint: object,
        params: object,
        status: object,
        authority: _JournalAuthorityRow | None,
    ) -> str:
        if type(status) is not str:
            return "failed"
        if status != "done":
            return status
        if self._done_authority_matches(
            endpoint,
            params,
            authority,
            require_receipt=False,
            require_w2_operation=False,
        ):
            return status
        return "failed"

    def _require_w2_admission(
        self,
        binding: LogicalCallReceiptBinding,
        admission: object,
    ) -> W2SourceCallAdmissionV1:
        from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1

        if type(admission) is not W2SourceCallAdmissionV1:
            raise ParserInputCaptureIntegrityError(
                "W2-required journal success requires one exact admission"
            )
        authority = _JournalAuthorityRow(
            logical_call_receipt_sha256=binding.logical_call_receipt_sha256,
            provider_authority_sha256=binding.provider_authority_sha256,
            logical_parameters_sha256=binding.logical_parameters_sha256,
            result_route_ids_json=json.dumps(
                list(binding.result_route_ids),
                separators=(",", ":"),
            ),
            w2_required=True,
            w2_source_call_admission_sha256=admission.admission_sha256,
            w2_source_call_admission_bytes=admission.canonical_bytes(),
            raw_authority_bundle_sha256=admission.raw_authority_bundle_sha256,
            raw_authority_persistence_receipt_sha256=(
                admission.raw_authority_persistence_receipt_sha256
            ),
            committed_staging_readback_count=(admission.committed_staging_readback_count),
            committed_staging_readback_root_sha256=(
                admission.committed_staging_readback_root_sha256
            ),
            w2_operation_key_sha256=admission.operation_key_sha256,
            w2_operation_receipt_sha256=admission.operation_receipt_sha256,
            w2_operation_persistence_receipt_sha256=(
                admission.w2_operation_persistence_receipt_sha256
            ),
        )
        verified = self._verified_w2_admission(authority, binding)
        if verified is None:
            raise ParserInputCaptureIntegrityError(
                "W2 journal admission does not match durable operation authority"
            ) from None
        return verified

    @staticmethod
    def _w2_update_values(
        admission: W2SourceCallAdmissionV1 | None,
    ) -> tuple[object, ...]:
        if admission is None:
            return (None,) * len(_W2_EVIDENCE_COLUMNS)
        return (
            admission.admission_sha256,
            admission.canonical_bytes(),
            admission.raw_authority_bundle_sha256,
            admission.raw_authority_persistence_receipt_sha256,
            admission.committed_staging_readback_count,
            admission.committed_staging_readback_root_sha256,
            admission.operation_key_sha256,
            admission.operation_receipt_sha256,
            admission.w2_operation_persistence_receipt_sha256,
        )

    # ── watermarks ────────────────────────────────────────────────

    def get_watermark(self, table: str, wtype: str) -> str | None:
        """Return the stored watermark value, or None."""
        row = self._conn.execute(
            """
            SELECT watermark_value
            FROM _pipeline_watermarks
            WHERE table_name = $1 AND watermark_type = $2
            """,
            [table, wtype],
        ).fetchone()
        return row[0] if row else None

    def set_watermark(
        self,
        table: str,
        wtype: str,
        value: str,
        row_count: int = 0,
    ) -> None:
        """Upsert a watermark value."""
        now = self._now_iso()
        self._conn.execute(
            """
            INSERT INTO _pipeline_watermarks
                (table_name, watermark_type, watermark_value,
                 last_updated, row_count_at_watermark)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (table_name, watermark_type)
            DO UPDATE SET
                watermark_value = EXCLUDED.watermark_value,
                last_updated = EXCLUDED.last_updated,
                row_count_at_watermark = EXCLUDED.row_count_at_watermark
            """,
            [table, wtype, value, now, row_count],
        )
        logger.debug(
            "watermark {}.{} = {} (rows={})",
            table,
            wtype,
            value,
            row_count,
        )

    # ── extraction journal ────────────────────────────────────────

    def record_start(
        self,
        endpoint: str,
        params: str,
        *,
        require_receipt: bool = False,
        require_w2_operation: bool = False,
    ) -> None:
        """Mark an extraction as started (in-progress)."""
        require_w2_operation = self._require_w2_flag(require_w2_operation)
        require_receipt = require_receipt or require_w2_operation
        now = self._now_iso()
        generation = self._successor_generation_sha256
        if generation is not None:
            require_receipt = True
            existing = self._conn.execute(
                f"""
                SELECT status,
                       {self._authority_projection()}
                FROM {_SUCCESSOR_JOURNAL_TABLE}
                WHERE successor_generation_sha256 = $1
                  AND endpoint = $2 AND params = $3
                """,
                [generation, endpoint, params],
            ).fetchone()
            if (
                existing is not None
                and existing[0] == "done"
                and self._done_authority_matches(
                    endpoint,
                    params,
                    self._authority_from_row(existing[1:]),
                    require_receipt=require_receipt,
                    require_w2_operation=require_w2_operation,
                )
            ):
                return
            if (
                existing is not None
                and existing[0] in {"running", "failed"}
                and self._promote_successor_replacement(
                    endpoint,
                    params,
                    require_w2_operation=require_w2_operation,
                )
            ):
                return
            self._conn.execute(
                f"""
                INSERT INTO {_SUCCESSOR_JOURNAL_TABLE}
                    (successor_generation_sha256, endpoint, params, status, started_at,
                     w2_required)
                VALUES ($1, $2, $3, 'running', $4, $5)
                ON CONFLICT (successor_generation_sha256, endpoint, params)
                DO UPDATE SET
                    status = 'running',
                    started_at = EXCLUDED.started_at,
                    completed_at = NULL,
                    rows_extracted = NULL,
                    error_message = NULL,
                    logical_call_receipt_sha256 = NULL,
                    provider_authority_sha256 = NULL,
                    logical_parameters_sha256 = NULL,
                    result_route_ids_json = NULL,
                    w2_required = EXCLUDED.w2_required,
                    w2_source_call_admission_sha256 = NULL,
                    w2_source_call_admission_bytes = NULL,
                    raw_authority_bundle_sha256 = NULL,
                    raw_authority_persistence_receipt_sha256 = NULL,
                    committed_staging_readback_count = NULL,
                    committed_staging_readback_root_sha256 = NULL,
                    w2_operation_key_sha256 = NULL,
                    w2_operation_receipt_sha256 = NULL,
                    w2_operation_persistence_receipt_sha256 = NULL
                """,
                [generation, endpoint, params, now, require_w2_operation],
            )
            return
        existing = self._conn.execute(
            f"""
            SELECT status,
                   {self._authority_projection()}
            FROM _extraction_journal
            WHERE endpoint = $1 AND params = $2
            """,
            [endpoint, params],
        ).fetchone()
        if (
            existing is not None
            and existing[0] == "done"
            and self._done_authority_matches(
                endpoint,
                params,
                self._authority_from_row(existing[1:]),
                require_receipt=require_receipt,
                require_w2_operation=require_w2_operation,
            )
        ):
            return
        self._conn.execute(
            """
            INSERT INTO _extraction_journal
                (endpoint, params, status, started_at, w2_required)
            VALUES ($1, $2, 'running', $3, $4)
            ON CONFLICT (endpoint, params)
            DO UPDATE SET
                status = 'running',
                started_at = EXCLUDED.started_at,
                completed_at = NULL,
                rows_extracted = NULL,
                error_message = NULL,
                logical_call_receipt_sha256 = NULL,
                provider_authority_sha256 = NULL,
                logical_parameters_sha256 = NULL,
                result_route_ids_json = NULL,
                w2_required = EXCLUDED.w2_required,
                w2_source_call_admission_sha256 = NULL,
                w2_source_call_admission_bytes = NULL,
                raw_authority_bundle_sha256 = NULL,
                raw_authority_persistence_receipt_sha256 = NULL,
                committed_staging_readback_count = NULL,
                committed_staging_readback_root_sha256 = NULL,
                w2_operation_key_sha256 = NULL,
                w2_operation_receipt_sha256 = NULL,
                w2_operation_persistence_receipt_sha256 = NULL
            """,
            [endpoint, params, now, require_w2_operation],
        )

    def record_success(
        self,
        endpoint: str,
        params: str,
        rows: int,
        *,
        receipt_binding: LogicalCallReceiptBinding | None = None,
        w2_admission: W2SourceCallAdmissionV1 | None = None,
    ) -> None:
        """Mark an extraction as successfully completed."""
        generation = self._successor_generation_sha256
        if generation is None:
            running_row = self._conn.execute(
                """
                SELECT status, w2_required
                FROM _extraction_journal
                WHERE endpoint = $1 AND params = $2
                """,
                [endpoint, params],
            ).fetchone()
        else:
            running_row = self._conn.execute(
                f"""
                SELECT status, w2_required
                FROM {_SUCCESSOR_JOURNAL_TABLE}
                WHERE successor_generation_sha256 = $1
                  AND endpoint = $2 AND params = $3
                """,
                [generation, endpoint, params],
            ).fetchone()
        if running_row is None or running_row[0] != "running":
            scope = "successor " if generation is not None else ""
            raise RuntimeError(f"{scope}journal success has no matching running row")
        if type(running_row[1]) is not bool:
            raise ParserInputCaptureIntegrityError(
                "journal running row has an invalid W2 requirement"
            )
        w2_required = running_row[1]
        if generation is not None and receipt_binding is None:
            raise ParserInputCaptureIntegrityError(
                "successor journal completion requires a logical-call receipt"
            )
        if w2_required and receipt_binding is None:
            raise ParserInputCaptureIntegrityError(
                "W2-required journal completion requires a logical-call receipt"
            )
        if not w2_required and w2_admission is not None:
            raise ParserInputCaptureIntegrityError(
                "journal admission differs from its running-row W2 requirement"
            )
        if receipt_binding is not None:
            if not self._receipt_binding_matches_endpoint(receipt_binding, endpoint):
                raise ParserInputCaptureIntegrityError(
                    "journal endpoint does not match the logical call routes"
                )
            if not self._receipt_binding_matches_params(receipt_binding, params):
                raise ParserInputCaptureIntegrityError(
                    "journal parameters do not match the logical call"
                )
            self._require_staging_receipt_binding(receipt_binding)
        verified_admission = (
            self._require_w2_admission(receipt_binding, w2_admission)
            if w2_required and receipt_binding is not None
            else None
        )
        now = self._now_iso()
        route_ids_json = (
            json.dumps(list(receipt_binding.result_route_ids), separators=(",", ":"))
            if receipt_binding is not None
            else None
        )
        authority_values: list[object] = [
            (receipt_binding.logical_call_receipt_sha256 if receipt_binding is not None else None),
            (receipt_binding.provider_authority_sha256 if receipt_binding is not None else None),
            (receipt_binding.logical_parameters_sha256 if receipt_binding is not None else None),
            route_ids_json,
            *self._w2_update_values(verified_admission),
        ]
        if generation is not None:
            result = self._conn.execute(
                f"""
                UPDATE {_SUCCESSOR_JOURNAL_TABLE}
                SET status = 'done',
                    completed_at = $1,
                    rows_extracted = $2,
                    error_message = NULL,
                    logical_call_receipt_sha256 = $3,
                    provider_authority_sha256 = $4,
                    logical_parameters_sha256 = $5,
                    result_route_ids_json = $6,
                    w2_source_call_admission_sha256 = $7,
                    w2_source_call_admission_bytes = $8,
                    raw_authority_bundle_sha256 = $9,
                    raw_authority_persistence_receipt_sha256 = $10,
                    committed_staging_readback_count = $11,
                    committed_staging_readback_root_sha256 = $12,
                    w2_operation_key_sha256 = $13,
                    w2_operation_receipt_sha256 = $14,
                    w2_operation_persistence_receipt_sha256 = $15
                WHERE successor_generation_sha256 = $16
                  AND endpoint = $17 AND params = $18
                  AND status = 'running'
                  AND w2_required = $19
                RETURNING 1
                """,
                [
                    now,
                    rows,
                    *authority_values,
                    generation,
                    endpoint,
                    params,
                    w2_required,
                ],
            ).fetchone()
            if result is None:
                raise RuntimeError("successor journal success has no matching running row")
            logger.info(
                "successor journal OK: {} [{}] -> {} rows ({})",
                endpoint,
                params,
                rows,
                generation,
            )
            return
        result = self._conn.execute(
            """
            UPDATE _extraction_journal
            SET status = 'done',
                completed_at = $1,
                rows_extracted = $2,
                error_message = NULL,
                logical_call_receipt_sha256 = $3,
                provider_authority_sha256 = $4,
                logical_parameters_sha256 = $5,
                result_route_ids_json = $6,
                w2_source_call_admission_sha256 = $7,
                w2_source_call_admission_bytes = $8,
                raw_authority_bundle_sha256 = $9,
                raw_authority_persistence_receipt_sha256 = $10,
                committed_staging_readback_count = $11,
                committed_staging_readback_root_sha256 = $12,
                w2_operation_key_sha256 = $13,
                w2_operation_receipt_sha256 = $14,
                w2_operation_persistence_receipt_sha256 = $15
            WHERE endpoint = $16 AND params = $17
              AND status = 'running'
              AND w2_required = $18
            RETURNING 1
            """,
            [
                now,
                rows,
                *authority_values,
                endpoint,
                params,
                w2_required,
            ],
        ).fetchone()
        if result is None:
            raise RuntimeError("journal success has no matching running row")
        logger.info(
            "journal OK: {} [{}] -> {} rows",
            endpoint,
            params,
            rows,
        )

    def record_failure(self, endpoint: str, params: str, error: str) -> None:
        """Mark an extraction as failed, incrementing the retry counter."""
        now = self._now_iso()
        generation = self._successor_generation_sha256
        if generation is not None:
            self._conn.execute(
                f"""
                UPDATE {_SUCCESSOR_JOURNAL_TABLE}
                SET status = 'failed',
                    completed_at = $1,
                    error_message = $2,
                    retry_count = retry_count + 1
                WHERE successor_generation_sha256 = $3
                  AND endpoint = $4 AND params = $5
                """,
                [now, error, generation, endpoint, params],
            )
            logger.warning(
                "successor journal FAIL: {} [{}] -> {} ({})",
                endpoint,
                params,
                error,
                generation,
            )
            return
        self._conn.execute(
            """
            UPDATE _extraction_journal
            SET status = 'failed',
                completed_at = $1,
                error_message = $2,
                retry_count = retry_count + 1
            WHERE endpoint = $3 AND params = $4
            """,
            [now, error, endpoint, params],
        )
        logger.warning(
            "journal FAIL: {} [{}] -> {}",
            endpoint,
            params,
            error,
        )

    def was_extracted(
        self,
        endpoint: str,
        params: str,
        *,
        require_receipt: bool = False,
        require_w2_operation: bool = False,
    ) -> bool:
        """Return True if this (endpoint, params) should be skipped.

        Only successful extractions are terminal. Failed, abandoned, and
        retry-capped rows remain replayable after a code fix or resume.
        """
        require_w2_operation = self._require_w2_flag(require_w2_operation)
        generation = self._successor_generation_sha256
        require_receipt = require_receipt or require_w2_operation or generation is not None
        if generation is not None:
            row = self._conn.execute(
                f"""
                SELECT status,
                       {self._authority_projection()}
                FROM {_SUCCESSOR_JOURNAL_TABLE}
                WHERE successor_generation_sha256 = $1
                  AND endpoint = $2
                  AND params = $3
                """,
                [generation, endpoint, params],
            ).fetchone()
            if row is None:
                return False
            if row[0] in {"running", "failed"}:
                return self._promote_successor_replacement(
                    endpoint,
                    params,
                    require_w2_operation=require_w2_operation,
                )
            if row[0] != "done":
                return False
            authority = self._authority_from_row(row[1:])
        else:
            row = self._conn.execute(
                f"""
                SELECT {self._authority_projection()}
                FROM _extraction_journal
                WHERE endpoint = $1
                  AND params = $2
                  AND status = 'done'
                """,
                [endpoint, params],
            ).fetchone()
            authority = self._authority_from_row(row)
        if row is None or authority is None:
            return False
        return self._done_authority_matches(
            endpoint,
            params,
            authority,
            require_receipt=require_receipt,
            require_w2_operation=require_w2_operation,
        )

    def has_done_entries(self, *, require_w2_operation: bool = False) -> bool:
        """Return True when any extraction has completed successfully."""
        require_w2_operation = self._require_w2_flag(require_w2_operation)
        generation = self._successor_generation_sha256
        if generation is not None:
            rows = self._conn.execute(
                f"""
                SELECT endpoint,
                       params,
                       {self._authority_projection()}
                FROM {_SUCCESSOR_JOURNAL_TABLE}
                WHERE successor_generation_sha256 = $1 AND status = 'done'
                """,
                [generation],
            ).fetchall()
            return any(
                self._done_authority_matches(
                    row[0],
                    row[1],
                    self._authority_from_row(row[2:]),
                    require_receipt=True,
                    require_w2_operation=require_w2_operation,
                )
                for row in rows
            )
        rows = self._conn.execute(
            f"""
            SELECT endpoint,
                   params,
                   {self._authority_projection()}
            FROM _extraction_journal
            WHERE status = 'done'
            """
        ).fetchall()
        return any(
            self._done_authority_matches(
                row[0],
                row[1],
                self._authority_from_row(row[2:]),
                require_receipt=require_w2_operation,
                require_w2_operation=require_w2_operation,
            )
            for row in rows
        )

    def load_successor_replacement_attestations(
        self,
    ) -> tuple[SourceScopeReplacementAttestation, ...]:
        """Reload every durable route replacement for this exact generation.

        This is the crash-recovery authority for provider calls persisted before
        process loss.  It validates each canonical replacement row, groups the
        rows back into exact logical calls, and proves parity with the live
        staging chunk journal before returning anything to the orchestrator.
        """

        generation = self._successor_generation_sha256
        if generation is None:
            raise RuntimeError(
                "successor replacement recovery requires successor_generation_sha256"
            )
        rows = self._conn.execute(
            """
            SELECT source_scope_sha256,
                   staging_key,
                   canonical_frame_format,
                   frame_content_hash_contract,
                   frame_schema_hash_contract,
                   prior_persisted_content_sha256,
                   persisted_content_sha256,
                   persisted_schema_sha256,
                   persisted_row_count,
                   logical_call_receipt_sha256,
                   provider_authority_sha256,
                   logical_parameters_sha256,
                   result_route_id,
                   replacement_sha256
            FROM _successor_staging_replacement_journal
            WHERE successor_generation_sha256 = $1
            ORDER BY logical_call_receipt_sha256, result_route_id
            """,
            [generation],
        ).fetchall()
        replacements: list[SourceScopeReplacementAttestation] = []
        by_root: dict[str, list[SourceScopeReplacementAttestation]] = {}
        try:
            for row in rows:
                replacement = SourceScopeReplacementAttestation(
                    successor_generation_sha256=generation,
                    source_scope_sha256=row[0],
                    staging_key=row[1],
                    canonical_frame_format=row[2],
                    frame_content_hash_contract=row[3],
                    frame_schema_hash_contract=row[4],
                    prior_persisted_content_sha256=row[5],
                    persisted_content_sha256=row[6],
                    persisted_schema_sha256=row[7],
                    persisted_row_count=row[8],
                    logical_call_receipt_sha256=row[9],
                    provider_authority_sha256=row[10],
                    logical_parameters_sha256=row[11],
                    result_route_id=row[12],
                )
                if (
                    replacement.replacement_sha256 != row[13]
                    or replacement.source_scope_sha256 != replacement.logical_parameters_sha256
                    or not self._replacement_route_matches(replacement)
                ):
                    raise ValueError("replacement row does not match its canonical authority")
                replacements.append(replacement)
                by_root.setdefault(replacement.logical_call_receipt_sha256, []).append(replacement)

            for root, logical_replacements in by_root.items():
                providers = {item.provider_authority_sha256 for item in logical_replacements}
                parameters = {item.logical_parameters_sha256 for item in logical_replacements}
                endpoints = {
                    item.result_route_id.rsplit(":", 2)[0] for item in logical_replacements
                }
                routes = tuple(sorted(item.result_route_id for item in logical_replacements))
                if (
                    len(providers) != 1
                    or len(parameters) != 1
                    or len(endpoints) != 1
                    or len(routes) != len(set(routes))
                ):
                    raise ValueError("replacement logical-call inventory is ambiguous")
                binding = LogicalCallReceiptBinding(
                    logical_call_receipt_sha256=root,
                    endpoint_name=next(iter(endpoints)),
                    logical_parameters_sha256=next(iter(parameters)),
                    provider_authority_sha256=next(iter(providers)),
                    result_route_ids=routes,
                )
                if not self._successor_staging_receipt_binding_matches(
                    generation,
                    binding,
                ) or not self._live_staging_inventory_matches(
                    binding,
                    logical_replacements,
                ):
                    raise ValueError(
                        "replacement logical-call inventory differs from durable staging"
                    )
        except (ParserInputCaptureIntegrityError, TypeError, ValueError) as exc:
            raise ParserInputCaptureIntegrityError(
                "successor replacement recovery inventory is invalid"
            ) from exc
        return tuple(replacements)

    def was_extracted_batch(
        self,
        items: list[tuple[str, str]],
        *,
        require_receipt: bool = False,
        require_w2_operation: bool = False,
    ) -> set[tuple[str, str]]:
        """Return the subset of (endpoint, params) pairs already done.

        Fetches all completed items from the journal in a single scan, then
        intersects with the requested set in Python.
        """
        if not items:
            return set()

        require_w2_operation = self._require_w2_flag(require_w2_operation)
        generation = self._successor_generation_sha256
        require_receipt = require_receipt or require_w2_operation or generation is not None
        if generation is not None:
            requested = set(items)
            recoverable = self._conn.execute(
                f"""
                SELECT endpoint, params
                FROM {_SUCCESSOR_JOURNAL_TABLE}
                WHERE successor_generation_sha256 = $1
                  AND status IN ('running', 'failed')
                """,
                [generation],
            ).fetchall()
            for endpoint, params in recoverable:
                if (endpoint, params) in requested:
                    self._promote_successor_replacement(
                        endpoint,
                        params,
                        require_w2_operation=require_w2_operation,
                    )
            rows = self._conn.execute(
                f"""
                SELECT endpoint,
                       params,
                       {self._authority_projection()}
                FROM {_SUCCESSOR_JOURNAL_TABLE}
                WHERE successor_generation_sha256 = $1 AND status = 'done'
                """,
                [generation],
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"""
                SELECT endpoint,
                       params,
                       {self._authority_projection()}
                FROM _extraction_journal
                WHERE status = 'done'
                """,
            ).fetchall()
        all_done = {
            (row[0], row[1])
            for row in rows
            if self._done_authority_matches(
                row[0],
                row[1],
                self._authority_from_row(row[2:]),
                require_receipt=require_receipt,
                require_w2_operation=require_w2_operation,
            )
        }
        return all_done & set(items)

    def _promote_successor_replacement(
        self,
        endpoint: str,
        params: str,
        *,
        require_w2_operation: bool = False,
    ) -> bool:
        """Promote one fully persisted successor call after an interrupted commit."""
        require_w2_operation = self._require_w2_flag(require_w2_operation)
        if require_w2_operation:
            return False
        generation = self._successor_generation_sha256
        if generation is None:
            return False
        try:
            decoded_params = json.loads(params)
            if not isinstance(decoded_params, dict):
                return False
            parameters_sha256 = canonical_parameters_sha256(decoded_params)
        except (json.JSONDecodeError, TypeError, ValueError):
            return False

        try:
            self._conn.execute("BEGIN TRANSACTION")
        except Exception as exc:
            raise RuntimeError(
                "successor replacement promotion requires transaction ownership"
            ) from exc
        transaction_started = True
        try:
            journal_row = self._conn.execute(
                f"""
                SELECT status, w2_required
                FROM {_SUCCESSOR_JOURNAL_TABLE}
                WHERE successor_generation_sha256 = $1
                  AND endpoint = $2
                  AND params = $3
                """,
                [generation, endpoint, params],
            ).fetchone()
            if (
                journal_row is None
                or journal_row[0] not in {"running", "failed"}
                or journal_row[1] is not False
            ):
                self._conn.execute("ROLLBACK")
                return False

            inventory = self._successor_replacement_inventory(
                generation,
                endpoint,
                parameters_sha256,
            )
            if inventory is None:
                self._conn.execute("ROLLBACK")
                return False
            binding, rows_extracted = inventory
            completed_at = self._now_iso()
            result = self._conn.execute(
                f"""
                UPDATE {_SUCCESSOR_JOURNAL_TABLE}
                SET status = 'done',
                    completed_at = $1,
                    rows_extracted = $2,
                    error_message = NULL,
                    logical_call_receipt_sha256 = $3,
                    provider_authority_sha256 = $4,
                    logical_parameters_sha256 = $5,
                    result_route_ids_json = $6,
                    w2_required = FALSE,
                    w2_source_call_admission_sha256 = NULL,
                    w2_source_call_admission_bytes = NULL,
                    raw_authority_bundle_sha256 = NULL,
                    raw_authority_persistence_receipt_sha256 = NULL,
                    committed_staging_readback_count = NULL,
                    committed_staging_readback_root_sha256 = NULL,
                    w2_operation_key_sha256 = NULL,
                    w2_operation_receipt_sha256 = NULL,
                    w2_operation_persistence_receipt_sha256 = NULL
                WHERE successor_generation_sha256 = $7
                  AND endpoint = $8
                  AND params = $9
                  AND status IN ('running', 'failed')
                RETURNING 1
                """,
                [
                    completed_at,
                    rows_extracted,
                    binding.logical_call_receipt_sha256,
                    binding.provider_authority_sha256,
                    binding.logical_parameters_sha256,
                    json.dumps(list(binding.result_route_ids), separators=(",", ":")),
                    generation,
                    endpoint,
                    params,
                ],
            ).fetchone()
            if result is None:
                self._conn.execute("ROLLBACK")
                return False
            self._conn.execute("COMMIT")
        except Exception:
            if transaction_started:
                with suppress(Exception):
                    self._conn.execute("ROLLBACK")
            return False

        logger.info(
            "recovered successor journal completion: {} [{}] -> {} rows ({})",
            endpoint,
            params,
            rows_extracted,
            generation,
        )
        return True

    def _successor_replacement_inventory(
        self,
        generation: str,
        endpoint: str,
        parameters_sha256: str,
    ) -> tuple[LogicalCallReceiptBinding, int] | None:
        rows = self._conn.execute(
            """
            SELECT source_scope_sha256,
                   staging_key,
                   canonical_frame_format,
                   frame_content_hash_contract,
                   frame_schema_hash_contract,
                   prior_persisted_content_sha256,
                   persisted_content_sha256,
                   persisted_schema_sha256,
                   persisted_row_count,
                   logical_call_receipt_sha256,
                   provider_authority_sha256,
                   logical_parameters_sha256,
                   result_route_id,
                   replacement_sha256
            FROM _successor_staging_replacement_journal
            WHERE successor_generation_sha256 = $1
              AND (source_scope_sha256 = $2 OR logical_parameters_sha256 = $2)
            """,
            [generation, parameters_sha256],
        ).fetchall()
        replacements: list[SourceScopeReplacementAttestation] = []
        for row in rows:
            raw_route = row[12]
            if not isinstance(raw_route, str):
                return None
            route_parts = raw_route.rsplit(":", 2)
            if len(route_parts) != 3:
                return None
            if route_parts[0] != endpoint:
                continue
            try:
                replacement = SourceScopeReplacementAttestation(
                    successor_generation_sha256=generation,
                    source_scope_sha256=row[0],
                    staging_key=row[1],
                    canonical_frame_format=row[2],
                    frame_content_hash_contract=row[3],
                    frame_schema_hash_contract=row[4],
                    prior_persisted_content_sha256=row[5],
                    persisted_content_sha256=row[6],
                    persisted_schema_sha256=row[7],
                    persisted_row_count=row[8],
                    logical_call_receipt_sha256=row[9],
                    provider_authority_sha256=row[10],
                    logical_parameters_sha256=row[11],
                    result_route_id=row[12],
                )
            except (ParserInputCaptureIntegrityError, TypeError, ValueError):
                return None
            if (
                replacement.replacement_sha256 != row[13]
                or replacement.source_scope_sha256 != parameters_sha256
                or replacement.logical_parameters_sha256 != parameters_sha256
                or not self._replacement_route_matches(replacement)
            ):
                return None
            replacements.append(replacement)

        if not replacements:
            return None
        receipts = {item.logical_call_receipt_sha256 for item in replacements}
        providers = {item.provider_authority_sha256 for item in replacements}
        routes = tuple(sorted(item.result_route_id for item in replacements))
        if len(receipts) != 1 or len(providers) != 1 or len(routes) != len(set(routes)):
            return None
        try:
            binding = LogicalCallReceiptBinding(
                logical_call_receipt_sha256=next(iter(receipts)),
                endpoint_name=endpoint,
                logical_parameters_sha256=parameters_sha256,
                provider_authority_sha256=next(iter(providers)),
                result_route_ids=routes,
            )
        except (TypeError, ValueError):
            return None
        if (
            not self._receipt_binding_matches_endpoint(binding, endpoint)
            or not self._successor_staging_receipt_binding_matches(generation, binding)
            or not self._live_staging_inventory_matches(binding, replacements)
        ):
            return None
        return binding, sum(item.persisted_row_count for item in replacements)

    def _live_staging_inventory_matches(
        self,
        binding: LogicalCallReceiptBinding,
        replacements: list[SourceScopeReplacementAttestation],
    ) -> bool:
        rows = self._conn.execute(
            """
            SELECT staging_key,
                   canonical_frame_format,
                   frame_content_hash_contract,
                   frame_schema_hash_contract,
                   persisted_row_count,
                   persisted_content_sha256,
                   persisted_schema_sha256,
                   provider_authority_sha256,
                   logical_parameters_sha256,
                   result_route_id
            FROM _staging_chunk_journal
            WHERE logical_call_receipt_sha256 = $1
            """,
            [binding.logical_call_receipt_sha256],
        ).fetchall()
        by_route = {item.result_route_id: item for item in replacements}
        if len(rows) != len(by_route):
            return False
        observed_routes: set[str] = set()
        for (
            staging_key,
            frame_format,
            content_contract,
            schema_contract,
            row_count,
            content,
            schema,
            provider,
            parameters,
            route,
        ) in rows:
            if not isinstance(route, str) or route in observed_routes:
                return False
            replacement = by_route.get(route)
            if replacement is None or (
                staging_key != replacement.staging_key
                or not _uses_v2_frame_contracts(
                    frame_format,
                    content_contract,
                    schema_contract,
                )
                or frame_format != replacement.canonical_frame_format
                or content_contract != replacement.frame_content_hash_contract
                or schema_contract != replacement.frame_schema_hash_contract
                or row_count != replacement.persisted_row_count
                or content != replacement.persisted_content_sha256
                or schema != replacement.persisted_schema_sha256
                or provider != binding.provider_authority_sha256
                or parameters != binding.logical_parameters_sha256
            ):
                return False
            observed_routes.add(route)
        return observed_routes == set(binding.result_route_ids)

    @staticmethod
    def _receipt_binding_from_row(row: tuple[object, ...]) -> LogicalCallReceiptBinding | None:
        if len(row) != 4 or any(not isinstance(value, str) for value in row):
            return None
        receipt, provider, parameters, raw_routes = row
        assert isinstance(receipt, str)
        assert isinstance(provider, str)
        assert isinstance(parameters, str)
        assert isinstance(raw_routes, str)
        if any(_SHA256_RE.fullmatch(value) is None for value in (receipt, provider, parameters)):
            return None
        try:
            decoded_routes = json.loads(raw_routes)
        except json.JSONDecodeError:
            return None
        if not isinstance(decoded_routes, list) or any(
            not isinstance(route, str) for route in decoded_routes
        ):
            return None
        route_endpoints = {
            route.rsplit(":", 2)[0] for route in decoded_routes if len(route.rsplit(":", 2)) == 3
        }
        if len(route_endpoints) != 1:
            return None
        try:
            return LogicalCallReceiptBinding(
                logical_call_receipt_sha256=receipt,
                endpoint_name=next(iter(route_endpoints)),
                logical_parameters_sha256=parameters,
                provider_authority_sha256=provider,
                result_route_ids=tuple(decoded_routes),
            )
        except ValueError:
            return None

    def _staging_receipt_binding_matches(
        self,
        binding: LogicalCallReceiptBinding,
    ) -> bool:
        generation = self._successor_generation_sha256
        if generation is not None:
            return self._successor_staging_receipt_binding_matches(
                generation,
                binding,
            )
        try:
            rows = self._conn.execute(
                """
                SELECT canonical_frame_format,
                       frame_content_hash_contract,
                       frame_schema_hash_contract,
                       provider_authority_sha256,
                       logical_parameters_sha256,
                       result_route_id,
                       persisted_row_count,
                       persisted_content_sha256,
                       persisted_schema_sha256
                FROM _staging_chunk_journal
                WHERE logical_call_receipt_sha256 = $1
                """,
                [binding.logical_call_receipt_sha256],
            ).fetchall()
        except Exception:
            return False
        expected_routes = set(binding.result_route_ids)
        if len(rows) != len(expected_routes):
            return False
        observed_routes: set[str] = set()
        for (
            frame_format,
            content_contract,
            schema_contract,
            provider,
            parameters,
            route,
            row_count,
            content,
            schema,
        ) in rows:
            if (
                not _uses_v2_frame_contracts(
                    frame_format,
                    content_contract,
                    schema_contract,
                )
                or provider != binding.provider_authority_sha256
                or parameters != binding.logical_parameters_sha256
                or not isinstance(route, str)
                or route in observed_routes
                or isinstance(row_count, bool)
                or not isinstance(row_count, int)
                or row_count < 0
                or not isinstance(content, str)
                or _SHA256_RE.fullmatch(content) is None
                or not isinstance(schema, str)
                or _SHA256_RE.fullmatch(schema) is None
            ):
                return False
            observed_routes.add(route)
        return observed_routes == expected_routes

    def _successor_staging_receipt_binding_matches(
        self,
        generation: str,
        binding: LogicalCallReceiptBinding,
    ) -> bool:
        try:
            rows = self._conn.execute(
                """
                SELECT source_scope_sha256,
                       staging_key,
                       canonical_frame_format,
                       frame_content_hash_contract,
                       frame_schema_hash_contract,
                       prior_persisted_content_sha256,
                       persisted_content_sha256,
                       persisted_schema_sha256,
                       persisted_row_count,
                       logical_call_receipt_sha256,
                       provider_authority_sha256,
                       logical_parameters_sha256,
                       result_route_id,
                       replacement_sha256
                FROM _successor_staging_replacement_journal
                WHERE successor_generation_sha256 = $1
                  AND logical_call_receipt_sha256 = $2
                """,
                [generation, binding.logical_call_receipt_sha256],
            ).fetchall()
        except Exception:
            return False
        expected_routes = set(binding.result_route_ids)
        if len(rows) != len(expected_routes):
            return False
        observed_routes: set[str] = set()
        for row in rows:
            try:
                replacement = SourceScopeReplacementAttestation(
                    successor_generation_sha256=generation,
                    source_scope_sha256=row[0],
                    staging_key=row[1],
                    canonical_frame_format=row[2],
                    frame_content_hash_contract=row[3],
                    frame_schema_hash_contract=row[4],
                    prior_persisted_content_sha256=row[5],
                    persisted_content_sha256=row[6],
                    persisted_schema_sha256=row[7],
                    persisted_row_count=row[8],
                    logical_call_receipt_sha256=row[9],
                    provider_authority_sha256=row[10],
                    logical_parameters_sha256=row[11],
                    result_route_id=row[12],
                )
            except (ParserInputCaptureIntegrityError, TypeError, ValueError):
                return False
            route = replacement.result_route_id
            if (
                replacement.replacement_sha256 != row[13]
                or replacement.logical_call_receipt_sha256 != binding.logical_call_receipt_sha256
                or replacement.provider_authority_sha256 != binding.provider_authority_sha256
                or replacement.logical_parameters_sha256 != binding.logical_parameters_sha256
                or not self._replacement_route_matches(replacement)
                or route in observed_routes
            ):
                return False
            observed_routes.add(route)
        return observed_routes == expected_routes

    @staticmethod
    def _replacement_route_matches(
        replacement: SourceScopeReplacementAttestation,
    ) -> bool:
        try:
            _endpoint, route_key, raw_index = replacement.result_route_id.rsplit(":", 2)
            result_index = int(raw_index)
        except (TypeError, ValueError):
            return False
        return (
            route_key == replacement.staging_key
            and result_index >= 0
            and raw_index == str(result_index)
        )

    @staticmethod
    def _receipt_binding_matches_endpoint(
        binding: LogicalCallReceiptBinding,
        endpoint: object,
    ) -> bool:
        if not isinstance(endpoint, str):
            return False
        if binding.endpoint_name != endpoint:
            return False
        for route in binding.result_route_ids:
            parts = route.rsplit(":", 2)
            if len(parts) != 3 or parts[0] != endpoint:
                return False
        return True

    @staticmethod
    def _receipt_binding_matches_params(
        binding: LogicalCallReceiptBinding,
        params: object,
    ) -> bool:
        if not isinstance(params, str):
            return False
        try:
            value = json.loads(params)
            return isinstance(value, dict) and (
                canonical_parameters_sha256(value) == binding.logical_parameters_sha256
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return False

    def _require_staging_receipt_binding(
        self,
        binding: LogicalCallReceiptBinding,
    ) -> None:
        if not self._staging_receipt_binding_matches(binding):
            raise ParserInputCaptureIntegrityError(
                "staging receipt inventory does not match the logical call"
            )

    MAX_RETRIES = 5

    def get_failed(
        self,
        *,
        include_exhausted: bool = False,
        include_abandoned: bool = False,
    ) -> list[tuple[str, str, str]]:
        """Return journal rows that should be retried.

        By default this returns non-exhausted failed rows only. Callers can opt
        into retry-capped failed rows and abandoned rows when they explicitly
        want a full replay pass.
        """
        params: list[object] = []
        generation_clause = ""
        retry_parameter = 1
        if self._successor_generation_sha256 is not None:
            generation_clause = "successor_generation_sha256 = $1 AND "
            params.append(self._successor_generation_sha256)
            retry_parameter = 2
        failed_clause = "status = 'failed'"
        if not include_exhausted:
            failed_clause += f" AND retry_count < ${retry_parameter}"
            params.append(self.MAX_RETRIES)

        status_clauses = [f"({failed_clause})"]
        if include_abandoned:
            status_clauses.append("(status = 'abandoned')")
        table = self._extraction_table
        rows = self._conn.execute(
            f"""
            SELECT endpoint, params, error_message
            FROM {table}
            WHERE {generation_clause}({" OR ".join(status_clauses)})
            ORDER BY started_at
            """,
            params,
        ).fetchall()
        return [(r[0], r[1], r[2] or "") for r in rows]

    def abandon_exhausted(self) -> int:
        """Mark failed entries that hit the retry cap as 'abandoned'. Returns count."""
        table = self._extraction_table
        generation_clause = ""
        query_params: list[object] = [self.MAX_RETRIES]
        if self._successor_generation_sha256 is not None:
            generation_clause = " AND successor_generation_sha256 = $2"
            query_params.append(self._successor_generation_sha256)
        result = self._conn.execute(
            f"""
            UPDATE {table}
            SET status = 'abandoned'
            WHERE status = 'failed' AND retry_count >= $1{generation_clause}
            """,
            query_params,
        )
        row = result.fetchone()
        count = row[0] if row else 0
        if count:
            logger.warning(
                "abandoned {} exhausted extractions (retry_count >= {})", count, self.MAX_RETRIES
            )
        return count

    def reset_stale_running(self, cutoff_minutes: int = 60) -> int:
        """Mark running entries older than cutoff as failed (stale from crash)."""
        table = self._extraction_table
        generation_clause = ""
        query_params: list[object] = [cutoff_minutes]
        if self._successor_generation_sha256 is not None:
            generation_clause = " AND successor_generation_sha256 = $2"
            query_params.append(self._successor_generation_sha256)
        result = self._conn.execute(
            f"""
            UPDATE {table}
            SET status = 'failed', error_message = 'stale_running'
            WHERE status = 'running'
            AND started_at < CURRENT_TIMESTAMP - INTERVAL (CAST($1 AS VARCHAR) || ' minutes')
            {generation_clause}
            """,
            query_params,
        )
        row = result.fetchone()
        count = row[0] if row else 0
        if count:
            logger.info("reset {} stale running entries to failed", count)
        return count

    def recover_interrupted_running(self, error: str = "interrupted_resume") -> int:
        """Convert lingering running rows into replayable failures.

        This is intended for single-runner resume flows where any leftover
        ``running`` rows necessarily belong to a prior interrupted process.
        """
        table = self._extraction_table
        generation_clause = ""
        count_params: list[object] = []
        if self._successor_generation_sha256 is not None:
            generation_clause = " AND successor_generation_sha256 = $1"
            count_params.append(self._successor_generation_sha256)
        row = self._conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {table}
            WHERE status = 'running'{generation_clause}
            """,
            count_params,
        ).fetchone()
        count = int(row[0]) if row else 0
        if count <= 0:
            return 0

        now = self._now_iso()
        update_generation_clause = ""
        update_params: list[object] = [now, error]
        if self._successor_generation_sha256 is not None:
            update_generation_clause = " AND successor_generation_sha256 = $3"
            update_params.append(self._successor_generation_sha256)
        self._conn.execute(
            f"""
            UPDATE {table}
            SET status = 'failed',
                completed_at = $1,
                error_message = $2
            WHERE status = 'running'{update_generation_clause}
            """,
            update_params,
        )
        logger.info("recovered {} interrupted running entries", count)
        return count

    def resume_summary(self, *, require_w2_operation: bool = False) -> dict[str, int]:
        """Return structured extraction summary for resume context display."""
        require_w2_operation = self._require_w2_flag(require_w2_operation)
        table = self._extraction_table
        generation = self._successor_generation_sha256
        if generation is None:
            rows = self._conn.execute(
                f"""
                SELECT endpoint,
                       params,
                       status,
                       rows_extracted,
                       {self._authority_projection()}
                FROM {table}
                """,
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"""
                SELECT endpoint,
                       params,
                       status,
                       rows_extracted,
                       {self._authority_projection()}
                FROM {table}
                WHERE successor_generation_sha256 = $1
                """,
                [generation],
            ).fetchall()
        summary = {
            "done": 0,
            "failed": 0,
            "running": 0,
            "abandoned": 0,
            "total_rows": 0,
        }
        for endpoint, params, status, row_count, *authority_row in rows:
            if status == "done":
                if self._done_authority_matches(
                    endpoint,
                    params,
                    self._authority_from_row(tuple(authority_row)),
                    require_receipt=(generation is not None or require_w2_operation),
                    require_w2_operation=require_w2_operation,
                ):
                    summary["done"] += 1
                    summary["total_rows"] += int(row_count or 0)
                else:
                    summary["failed"] += 1
            elif status in {"failed", "running", "abandoned"}:
                summary[status] += 1
        return summary

    def error_breakdown(self, limit: int = 10) -> list[tuple[str, int]]:
        """Return top failure error messages with counts."""
        table = self._extraction_table
        generation_clause = ""
        query_params: list[object] = []
        limit_position = 1
        if self._successor_generation_sha256 is not None:
            generation_clause = "AND successor_generation_sha256 = $1"
            query_params.append(self._successor_generation_sha256)
            limit_position = 2
        query_params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT error_message, COUNT(*) AS cnt
            FROM {table}
            WHERE status = 'failed'
            {generation_clause}
            GROUP BY error_message
            ORDER BY cnt DESC
            LIMIT ${limit_position}
            """,
            query_params,
        ).fetchall()
        return [(r[0] or "Unknown", r[1]) for r in rows]

    def log_summary(self) -> None:
        """Log a summary of extraction results at INFO level."""
        s = self.resume_summary()
        logger.info(
            "extraction journal summary: {} done ({} rows), {} failed, {} abandoned, {} running",
            s["done"],
            s["total_rows"],
            s["failed"],
            s["abandoned"],
            s["running"],
        )
        if s["failed"] > 0:
            for error_msg, cnt in self.error_breakdown():
                logger.info("  failure: {} x{}", error_msg, cnt)

    def clear_journal(self) -> None:
        """Delete all journal entries (for fresh runs)."""
        if self._successor_generation_sha256 is None:
            self._conn.execute("DELETE FROM _extraction_journal")
        else:
            self._conn.execute(
                f"DELETE FROM {_SUCCESSOR_JOURNAL_TABLE} WHERE successor_generation_sha256 = $1",
                [self._successor_generation_sha256],
            )
        logger.info("extraction journal cleared")

    # ── selective journal operations (backfill) ────────────────────

    @staticmethod
    def _build_filter_clause(
        *,
        endpoint: str | list[str] | None = None,
        status_filter: str | None = None,
        season_like: str | None = None,
    ) -> tuple[str, list[str | int]]:
        """Build a WHERE clause from AND-combined filters.

        Returns (where_sql, params).  At least one filter must be non-None.

        ``endpoint`` accepts a single string or a list for batched
        ``IN (...)`` queries.
        """
        clauses: list[str] = []
        params: list[str | int] = []
        idx = 1

        if endpoint is not None:
            if isinstance(endpoint, list):
                placeholders = ", ".join(f"${idx + i}" for i in range(len(endpoint)))
                clauses.append(f"endpoint IN ({placeholders})")
                params.extend(endpoint)
                idx += len(endpoint)
            else:
                clauses.append(f"endpoint = ${idx}")
                params.append(endpoint)
                idx += 1

        if status_filter is not None:
            clauses.append(f"status = ${idx}")
            params.append(status_filter)
            idx += 1

        if season_like is not None:
            escaped = season_like.replace("%", "\\%").replace("_", "\\_")
            clauses.append(f"params LIKE ${idx} ESCAPE '\\'")
            params.append(f'%"season": "{escaped}"%')
            idx += 1

        if not clauses:
            raise ValueError("at least one filter must be provided")

        return " AND ".join(clauses), params

    def reset_entries(
        self,
        *,
        endpoint: str | list[str] | None = None,
        status_filter: str | None = None,
        season_like: str | None = None,
    ) -> int:
        """Reset matching journal entries to ``failed`` with ``retry_count=0``.

        Makes entries eligible for re-extraction by the runner.
        Filters are AND-combined; at least one must be provided.
        Returns the number of entries reset.
        """
        self._require_baseline_extraction_journal("reset_entries")
        where, params = self._build_filter_clause(
            endpoint=endpoint,
            status_filter=status_filter,
            season_like=season_like,
        )
        result = self._conn.execute(
            f"""
            UPDATE _extraction_journal
            SET status = 'failed',
                retry_count = 0,
                error_message = 'backfill_reset',
                logical_call_receipt_sha256 = NULL,
                provider_authority_sha256 = NULL,
                logical_parameters_sha256 = NULL,
                result_route_ids_json = NULL,
                w2_required = FALSE,
                w2_source_call_admission_sha256 = NULL,
                w2_source_call_admission_bytes = NULL,
                raw_authority_bundle_sha256 = NULL,
                raw_authority_persistence_receipt_sha256 = NULL,
                committed_staging_readback_count = NULL,
                committed_staging_readback_root_sha256 = NULL,
                w2_operation_key_sha256 = NULL,
                w2_operation_receipt_sha256 = NULL,
                w2_operation_persistence_receipt_sha256 = NULL
            WHERE {where}
            """,
            params,
        )
        row = result.fetchone()
        count = row[0] if row else 0
        logger.info(
            "reset {} journal entries (endpoint={}, status={}, season={})",
            count,
            endpoint,
            status_filter,
            season_like,
        )
        return count

    def clear_entries(
        self,
        *,
        endpoint: str | list[str] | None = None,
        status_filter: str | None = None,
        season_like: str | None = None,
    ) -> int:
        """Delete matching journal entries.

        Filters are AND-combined; at least one must be provided.
        Returns the number of entries deleted.
        """
        self._require_baseline_extraction_journal("clear_entries")
        where, params = self._build_filter_clause(
            endpoint=endpoint,
            status_filter=status_filter,
            season_like=season_like,
        )
        result = self._conn.execute(
            f"""
            DELETE FROM _extraction_journal
            WHERE {where}
            """,
            params,
        )
        row = result.fetchone()
        count = row[0] if row else 0
        logger.info(
            "cleared {} journal entries (endpoint={}, status={}, season={})",
            count,
            endpoint,
            status_filter,
            season_like,
        )
        return count

    def count_by_endpoint_and_status(self) -> list[tuple[str, str, int]]:
        """Return ``(endpoint, status, count)`` grouped rows."""
        self._require_baseline_extraction_journal("count_by_endpoint_and_status")
        rows = self._conn.execute(
            f"""
            SELECT endpoint,
                   params,
                   status,
                   {self._authority_projection()}
            FROM _extraction_journal
            """
        ).fetchall()
        counts: dict[tuple[str, str], int] = {}
        for endpoint, params, status, *authority_row in rows:
            effective_status = self._effective_status(
                endpoint,
                params,
                status,
                self._authority_from_row(tuple(authority_row)),
            )
            key = (endpoint, effective_status)
            counts[key] = counts.get(key, 0) + 1
        return [(endpoint, status, count) for (endpoint, status), count in sorted(counts.items())]

    def count_done_by_endpoint_and_season(self) -> list[tuple[str, str | None, int]]:
        """Return ``(endpoint, season, done_count)`` flattened across season types."""
        self._require_baseline_extraction_journal("count_done_by_endpoint_and_season")
        counts: dict[tuple[str, str | None], int] = {}
        for endpoint, season, _season_type, done_count in self.count_done_by_endpoint_season_type():
            key = (endpoint, season)
            counts[key] = counts.get(key, 0) + done_count

        return [
            (endpoint, season, done_count)
            for (endpoint, season), done_count in sorted(counts.items())
        ]

    def count_done_by_endpoint_season_type(
        self,
    ) -> list[tuple[str, str | None, str | None, int]]:
        """Return ``(endpoint, season, season_type, done_count)`` using JSON extraction."""
        self._require_baseline_extraction_journal("count_done_by_endpoint_season_type")
        rows = self._conn.execute(
            f"""
            SELECT
                endpoint,
                params,
                json_extract_string(params, '$.season')      AS season,
                json_extract_string(params, '$.season_type') AS season_type,
                {self._authority_projection()}
            FROM _extraction_journal
            WHERE status = 'done'
            """
        ).fetchall()
        counts: dict[tuple[str, str | None, str | None], int] = {}
        for endpoint, params, season, season_type, *authority_row in rows:
            if not self._done_authority_matches(
                endpoint,
                params,
                self._authority_from_row(tuple(authority_row)),
                require_receipt=False,
                require_w2_operation=False,
            ):
                continue
            key = (endpoint, season, season_type)
            counts[key] = counts.get(key, 0) + 1
        return [
            (endpoint, season, season_type, done_count)
            for (endpoint, season, season_type), done_count in sorted(
                counts.items(),
                key=lambda item: tuple("" if part is None else part for part in item[0]),
            )
        ]

    def fetch_entries(
        self,
        *,
        endpoints: list[str] | None = None,
        seasons: list[str] | None = None,
        status_filter: str | None = None,
        limit: int = 100,
    ) -> list[tuple[str, str, str, int, str]]:
        """Query journal entries with optional filters.

        Returns ``(endpoint, params, status, retry_count, started_at)`` tuples.
        """
        self._require_baseline_extraction_journal("fetch_entries")
        clauses: list[str] = []
        params: list[str | int] = []
        idx = 1

        if endpoints:
            placeholders = ", ".join(f"${idx + i}" for i in range(len(endpoints)))
            clauses.append(f"endpoint IN ({placeholders})")
            params.extend(endpoints)
            idx += len(endpoints)

        if status_filter:
            clauses.append(f"status = ${idx}")
            params.append(status_filter)
            idx += 1

        if seasons:
            season_clauses = []
            for season in seasons:
                escaped = season.replace("%", "\\%").replace("_", "\\_")
                season_clauses.append(f"params LIKE ${idx} ESCAPE '\\'")
                params.append(f'%"season": "{escaped}"%')
                idx += 1
            clauses.append(f"({' OR '.join(season_clauses)})")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT endpoint,
                   params,
                   status,
                   retry_count,
                   started_at,
                   {self._authority_projection()}
            FROM _extraction_journal {where}
            ORDER BY endpoint, started_at
            LIMIT ${idx}
            """,
            params,
        ).fetchall()
        entries: list[tuple[str, str, str, int, str]] = []
        for row in rows:
            effective_status = self._effective_status(
                row[0],
                row[1],
                row[2],
                self._authority_from_row(row[5:]),
            )
            if status_filter is not None and effective_status != status_filter:
                continue
            entries.append((row[0], row[1], effective_status, row[3], str(row[4])))
        return entries

    # ── table metadata ────────────────────────────────────────────

    def record_table_metadata(
        self,
        table: str,
        row_count: int,
        schema_hash: str,
        *,
        quality_score: float | None = None,
    ) -> None:
        """Upsert per-table inventory metadata for status and agent surfaces."""
        now = self._now_iso()
        self._conn.execute(
            """
            INSERT INTO _pipeline_metadata
                (table_name, last_updated, row_count, schema_hash, quality_score)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (table_name)
            DO UPDATE SET
                last_updated = EXCLUDED.last_updated,
                row_count = EXCLUDED.row_count,
                schema_hash = EXCLUDED.schema_hash,
                quality_score = EXCLUDED.quality_score
            """,
            [table, now, row_count, schema_hash, quality_score],
        )
        logger.debug(
            "metadata {} rows={} schema_hash={}",
            table,
            row_count,
            schema_hash,
        )

    def get_table_metadata(self, table: str) -> tuple[int, str, str, float | None] | None:
        """Return (row_count, schema_hash, last_updated, quality_score) for a table."""
        row = self._conn.execute(
            """
            SELECT row_count, schema_hash, last_updated, quality_score
            FROM _pipeline_metadata
            WHERE table_name = $1
            """,
            [table],
        ).fetchone()
        if row is None:
            return None
        quality_score = None if row[3] is None else float(row[3])
        return (int(row[0]), str(row[1]), str(row[2]), quality_score)

    # ── pipeline metrics ──────────────────────────────────────────

    def record_metric(
        self,
        endpoint: str,
        duration: float,
        rows: int,
        errors: int = 0,
    ) -> None:
        """Record a run metric for the given endpoint."""
        now = self._now_iso()
        self._conn.execute(
            """
            INSERT INTO _pipeline_metrics
                (endpoint, run_timestamp, duration_seconds,
                 rows_extracted, error_count)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (endpoint, run_timestamp)
            DO UPDATE SET
                duration_seconds = EXCLUDED.duration_seconds,
                rows_extracted = EXCLUDED.rows_extracted,
                error_count = EXCLUDED.error_count
            """,
            [endpoint, now, duration, rows, errors],
        )

    def record_lane_metric(
        self,
        *,
        lane_id: str,
        run_mode: str,
        pattern: str,
        endpoint_families: list[str],
        started_at: datetime,
        completed_at: datetime,
        wall_time_seconds: float,
        task_count: int,
        row_count: int,
        success_count: int,
        failure_count: int,
        retry_inflation: float = 0.0,
        queue_wait_seconds: float = 0.0,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO _lane_metrics (
                lane_id, run_mode, pattern, endpoint_families,
                started_at, completed_at, wall_time_seconds,
                task_count, row_count, success_count, failure_count,
                retry_inflation, queue_wait_seconds
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (lane_id)
            DO UPDATE SET
                run_mode = EXCLUDED.run_mode,
                pattern = EXCLUDED.pattern,
                endpoint_families = EXCLUDED.endpoint_families,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                wall_time_seconds = EXCLUDED.wall_time_seconds,
                task_count = EXCLUDED.task_count,
                row_count = EXCLUDED.row_count,
                success_count = EXCLUDED.success_count,
                failure_count = EXCLUDED.failure_count,
                retry_inflation = EXCLUDED.retry_inflation,
                queue_wait_seconds = EXCLUDED.queue_wait_seconds
            """,
            [
                lane_id,
                run_mode,
                pattern,
                json.dumps(endpoint_families),
                started_at.isoformat(),
                completed_at.isoformat(),
                wall_time_seconds,
                task_count,
                row_count,
                success_count,
                failure_count,
                retry_inflation,
                queue_wait_seconds,
            ],
        )
