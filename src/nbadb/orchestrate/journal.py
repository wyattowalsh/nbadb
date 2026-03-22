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
        """Mark an extraction as failed, incrementing the retry counter."""
        now = datetime.now(UTC).isoformat()
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

    def was_extracted(self, endpoint: str, params: str) -> bool:
        """Return True if this (endpoint, params) should be skipped.

        Skips entries that are done, abandoned, or have exhausted the retry cap
        (retry_count >= MAX_RETRIES) even before abandon_exhausted() is called.
        """
        row = self._conn.execute(
            """
            SELECT 1 FROM _extraction_journal
            WHERE endpoint = $1
              AND params = $2
              AND (status IN ('done', 'abandoned') OR retry_count >= $3)
            """,
            [endpoint, params, self.MAX_RETRIES],
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
        n = len(items)
        placeholders = ", ".join(f"(${i * 2 + 1}, ${i * 2 + 2})" for i in range(n))
        retry_param_idx = n * 2 + 1
        flat_params: list[str] = []
        for endpoint, params in items:
            flat_params.append(endpoint)
            flat_params.append(params)
        flat_params.append(self.MAX_RETRIES)

        rows = self._conn.execute(
            f"""
            SELECT endpoint, params
            FROM _extraction_journal
            WHERE (status IN ('done', 'abandoned') OR retry_count >= ${retry_param_idx})
              AND (endpoint, params) IN ({placeholders})
            """,
            flat_params,
        ).fetchall()
        return {(r[0], r[1]) for r in rows}

    MAX_RETRIES = 5

    def get_failed(self) -> list[tuple[str, str, str]]:
        """Return failed extractions that haven't exceeded the retry cap."""
        rows = self._conn.execute(
            """
            SELECT endpoint, params, error_message
            FROM _extraction_journal
            WHERE status = 'failed'
              AND retry_count < $1
            ORDER BY started_at
            """,
            [self.MAX_RETRIES],
        ).fetchall()
        return [(r[0], r[1], r[2] or "") for r in rows]

    def abandon_exhausted(self) -> int:
        """Mark failed entries that hit the retry cap as 'abandoned'. Returns count."""
        result = self._conn.execute(
            """
            UPDATE _extraction_journal
            SET status = 'abandoned'
            WHERE status = 'failed' AND retry_count >= $1
            """,
            [self.MAX_RETRIES],
        )
        count = result.rowcount or 0
        if count:
            logger.warning(
                "abandoned {} exhausted extractions (retry_count >= {})", count, self.MAX_RETRIES
            )
        return count

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
                COUNT(*) FILTER (WHERE status = 'abandoned') AS abandoned,
                COALESCE(SUM(rows_extracted) FILTER (WHERE status = 'done'), 0) AS total_rows
            FROM _extraction_journal
            """
        ).fetchone()
        done, failed, running, abandoned, total_rows = row
        logger.info(
            "extraction journal summary: {} done ({} rows), {} failed, {} abandoned, {} running",
            done,
            total_rows,
            failed,
            abandoned,
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

    # ── selective journal operations (backfill) ────────────────────

    @staticmethod
    def _build_filter_clause(
        *,
        endpoint: str | None = None,
        status_filter: str | None = None,
        season_like: str | None = None,
    ) -> tuple[str, list[str]]:
        """Build a WHERE clause from AND-combined filters.

        Returns (where_sql, params).  At least one filter must be non-None.
        """
        clauses: list[str] = []
        params: list[str] = []
        idx = 1

        if endpoint is not None:
            clauses.append(f"endpoint = ${idx}")
            params.append(endpoint)
            idx += 1

        if status_filter is not None:
            clauses.append(f"status = ${idx}")
            params.append(status_filter)
            idx += 1

        if season_like is not None:
            clauses.append(f"params LIKE ${idx}")
            params.append(f'%"season": "{season_like}"%')
            idx += 1

        if not clauses:
            raise ValueError("at least one filter must be provided")

        return " AND ".join(clauses), params

    def reset_entries(
        self,
        *,
        endpoint: str | None = None,
        status_filter: str | None = None,
        season_like: str | None = None,
    ) -> int:
        """Reset matching journal entries to ``failed`` with ``retry_count=0``.

        Makes entries eligible for re-extraction by the runner.
        Filters are AND-combined; at least one must be provided.
        Returns the number of entries reset.
        """
        where, params = self._build_filter_clause(
            endpoint=endpoint,
            status_filter=status_filter,
            season_like=season_like,
        )
        result = self._conn.execute(
            f"""
            UPDATE _extraction_journal
            SET status = 'failed', retry_count = 0, error_message = 'backfill_reset'
            WHERE {where}
            """,
            params,
        )
        count = result.rowcount or 0
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
        endpoint: str | None = None,
        status_filter: str | None = None,
        season_like: str | None = None,
    ) -> int:
        """Delete matching journal entries.

        Filters are AND-combined; at least one must be provided.
        Returns the number of entries deleted.
        """
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
        count = result.rowcount or 0
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
        rows = self._conn.execute(
            """
            SELECT endpoint, status, COUNT(*) AS cnt
            FROM _extraction_journal
            GROUP BY endpoint, status
            ORDER BY endpoint, status
            """
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

    def count_done_by_endpoint_and_season(self) -> list[tuple[str, str | None, int]]:
        """Return ``(endpoint, season, done_count)`` using JSON extraction.

        Uses DuckDB ``json_extract_string`` on the params column to group
        by season without Python-side JSON parsing.
        """
        rows = self._conn.execute(
            """
            SELECT
                endpoint,
                json_extract_string(params, '$.season') AS season,
                COUNT(*) AS done_count
            FROM _extraction_journal
            WHERE status = 'done'
            GROUP BY endpoint, json_extract_string(params, '$.season')
            ORDER BY endpoint, season
            """
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]

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
