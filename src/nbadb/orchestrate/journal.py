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
            WHERE _extraction_journal.status != 'done'
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

        Only successful extractions are terminal. Failed, abandoned, and
        retry-capped rows remain replayable after a code fix or resume.
        """
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

        Fetches all completed items from the journal in a single scan, then
        intersects with the requested set in Python.
        """
        if not items:
            return set()

        rows = self._conn.execute(
            """
            SELECT endpoint, params
            FROM _extraction_journal
            WHERE status = 'done'
            """,
        ).fetchall()
        all_done = {(r[0], r[1]) for r in rows}
        return all_done & set(items)

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
        failed_clause = "status = 'failed'"
        if not include_exhausted:
            failed_clause += " AND retry_count < $1"
            params.append(self.MAX_RETRIES)

        status_clauses = [f"({failed_clause})"]
        if include_abandoned:
            status_clauses.append("(status = 'abandoned')")
        rows = self._conn.execute(
            f"""
            SELECT endpoint, params, error_message
            FROM _extraction_journal
            WHERE {" OR ".join(status_clauses)}
            ORDER BY started_at
            """,
            params,
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
        row = result.fetchone()
        count = row[0] if row else 0
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
        row = self._conn.execute(
            """
            SELECT COUNT(*)
            FROM _extraction_journal
            WHERE status = 'running'
            """
        ).fetchone()
        count = int(row[0]) if row else 0
        if count <= 0:
            return 0

        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            UPDATE _extraction_journal
            SET status = 'failed',
                completed_at = $1,
                error_message = $2
            WHERE status = 'running'
            """,
            [now, error],
        )
        logger.info("recovered {} interrupted running entries", count)
        return count

    def resume_summary(self) -> dict[str, int]:
        """Return structured extraction summary for resume context display."""
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
        if row is None:
            return {"done": 0, "failed": 0, "running": 0, "abandoned": 0, "total_rows": 0}
        return {
            "done": row[0],
            "failed": row[1],
            "running": row[2],
            "abandoned": row[3],
            "total_rows": row[4],
        }

    def error_breakdown(self, limit: int = 10) -> list[tuple[str, int]]:
        """Return top failure error messages with counts."""
        rows = self._conn.execute(
            """
            SELECT error_message, COUNT(*) AS cnt
            FROM _extraction_journal
            WHERE status = 'failed'
            GROUP BY error_message
            ORDER BY cnt DESC
            LIMIT $1
            """,
            [limit],
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
        self._conn.execute("DELETE FROM _extraction_journal")
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
            SELECT endpoint, params, status, retry_count, started_at
            FROM _extraction_journal {where}
            ORDER BY endpoint, started_at
            LIMIT ${idx}
            """,
            params,
        ).fetchall()
        return [(r[0], r[1], r[2], r[3], str(r[4])) for r in rows]

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
