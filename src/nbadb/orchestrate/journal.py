from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import duckdb


class PipelineJournal:
    """Thin wrapper around the DuckDB pipeline tables.

    Tables are created by ``DBManager._create_pipeline_tables()``.
    This class only reads/writes; it never creates schema.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

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
        now = datetime.now(UTC).isoformat()
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

    def record_start(self, endpoint: str, params: str) -> None:
        """Mark an extraction as started (in-progress)."""
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO _extraction_journal
                (endpoint, params, status, started_at)
            VALUES ($1, $2, 'running', $3)
            ON CONFLICT (endpoint, params)
            DO UPDATE SET
                status = 'running',
                started_at = EXCLUDED.started_at,
                completed_at = NULL,
                rows_extracted = NULL,
                error_message = NULL
            """,
            [endpoint, params, now],
        )

    def record_success(self, endpoint: str, params: str, rows: int) -> None:
        """Mark an extraction as successfully completed."""
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            UPDATE _extraction_journal
            SET status = 'done',
                completed_at = $1,
                rows_extracted = $2,
                error_message = NULL
            WHERE endpoint = $3 AND params = $4
            """,
            [now, rows, endpoint, params],
        )
        logger.info(
            "journal OK: {} [{}] -> {} rows",
            endpoint,
            params,
            rows,
        )

    def record_failure(self, endpoint: str, params: str, error: str) -> None:
        """Mark an extraction as failed."""
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            UPDATE _extraction_journal
            SET status = 'failed',
                completed_at = $1,
                error_message = $2
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

    def was_extracted(self, endpoint: str, params: str) -> bool:
        """Return True if this (endpoint, params) completed successfully."""
        row = self._conn.execute(
            """
            SELECT 1 FROM _extraction_journal
            WHERE endpoint = $1
              AND params = $2
              AND status = 'done'
            """,
            [endpoint, params],
        ).fetchone()
        return row is not None

    def has_done_entries(self) -> bool:
        """Return True when any extraction has completed successfully."""
        row = self._conn.execute(
            """
            SELECT 1
            FROM _extraction_journal
            WHERE status = 'done'
            LIMIT 1
            """
        ).fetchone()
        return row is not None

    def was_extracted_batch(self, items: list[tuple[str, str]]) -> set[tuple[str, str]]:
        """Return the subset of (endpoint, params) pairs already done.

        Fetches all already-completed items in a single query instead
        of one query per item (avoids the N+1 pattern).
        """
        if not items:
            return set()

        # Build parameterized placeholders: ($1, $2), ($3, $4), ...
        placeholders = ", ".join(f"(${i * 2 + 1}, ${i * 2 + 2})" for i in range(len(items)))
        flat_params: list[str] = []
        for endpoint, params in items:
            flat_params.append(endpoint)
            flat_params.append(params)

        rows = self._conn.execute(
            f"""
            SELECT endpoint, params
            FROM _extraction_journal
            WHERE status = 'done'
              AND (endpoint, params) IN ({placeholders})
            """,
            flat_params,
        ).fetchall()
        return {(r[0], r[1]) for r in rows}

    def get_failed(self) -> list[tuple[str, str, str]]:
        """Return all failed extractions as (endpoint, params, error)."""
        rows = self._conn.execute(
            """
            SELECT endpoint, params, error_message
            FROM _extraction_journal
            WHERE status = 'failed'
            ORDER BY started_at
            """
        ).fetchall()
        return [(r[0], r[1], r[2] or "") for r in rows]

    def reset_stale_running(self, cutoff_minutes: int = 60) -> int:
        """Mark running entries older than cutoff as failed (stale from crash)."""
        result = self._conn.execute(
            """
            UPDATE _extraction_journal
            SET status = 'failed', error_message = 'stale_running'
            WHERE status = 'running'
            AND started_at < CURRENT_TIMESTAMP - INTERVAL (CAST(? AS VARCHAR) || ' minutes')
            """,
            [cutoff_minutes],
        )
        count = result.rowcount or 0
        if count:
            logger.info("reset {} stale running entries to failed", count)
        return count

    def log_summary(self) -> None:
        """Log a summary of extraction results at INFO level."""
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'done') AS done,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COUNT(*) FILTER (WHERE status = 'running') AS running,
                COALESCE(SUM(rows_extracted) FILTER (WHERE status = 'done'), 0) AS total_rows
            FROM _extraction_journal
            """
        ).fetchone()
        done, failed, running, total_rows = row
        logger.info(
            "extraction journal summary: {} done ({} rows), {} failed, {} running",
            done,
            total_rows,
            failed,
            running,
        )
        if failed > 0:
            # Log top failure reasons
            error_rows = self._conn.execute(
                """
                SELECT error_message, COUNT(*) AS cnt
                FROM _extraction_journal
                WHERE status = 'failed'
                GROUP BY error_message
                ORDER BY cnt DESC
                LIMIT 10
                """
            ).fetchall()
            for error_msg, cnt in error_rows:
                logger.info("  failure: {} x{}", error_msg, cnt)

    def clear_journal(self) -> None:
        """Delete all journal entries (for fresh runs)."""
        self._conn.execute("DELETE FROM _extraction_journal")
        logger.info("extraction journal cleared")

    # ── pipeline metrics ──────────────────────────────────────────

    def record_metric(
        self,
        endpoint: str,
        duration: float,
        rows: int,
        errors: int = 0,
    ) -> None:
        """Record a run metric for the given endpoint."""
        now = datetime.now(UTC).isoformat()
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
