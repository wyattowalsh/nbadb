"""Transform pipeline metrics collection and reporting.

Captures per-transformer timing, row counts, and error details.
Provides a structured summary for post-run analysis.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import duckdb


@dataclass
class TransformerMetric:
    """Timing and output metrics for a single transformer execution."""

    table_name: str
    started_at: float  # time.perf_counter() value
    completed_at: float | None = None
    row_count: int = 0
    column_count: int = 0
    status: str = "pending"  # pending, success, failed, skipped
    error_message: str | None = None

    @property
    def duration_seconds(self) -> float:
        if self.completed_at is None:
            return 0.0
        return self.completed_at - self.started_at


@dataclass
class PipelineMetrics:
    """Collects and reports metrics for an entire pipeline run."""

    run_id: str
    started_at: float = field(default_factory=time.perf_counter)
    completed_at: float | None = None
    transformers: dict[str, TransformerMetric] = field(default_factory=dict)

    def start_transformer(self, table_name: str) -> None:
        """Record the start of a transformer execution."""
        self.transformers[table_name] = TransformerMetric(
            table_name=table_name,
            started_at=time.perf_counter(),
        )

    def complete_transformer(
        self,
        table_name: str,
        row_count: int,
        column_count: int,
    ) -> None:
        """Record successful completion of a transformer."""
        metric = self.transformers.get(table_name)
        if metric is None:
            return
        metric.completed_at = time.perf_counter()
        metric.row_count = row_count
        metric.column_count = column_count
        metric.status = "success"
        logger.debug(
            "metric: {} completed in {:.2f}s ({} rows, {} cols)",
            table_name,
            metric.duration_seconds,
            row_count,
            column_count,
        )

    def fail_transformer(self, table_name: str, error: str) -> None:
        """Record a transformer failure."""
        metric = self.transformers.get(table_name)
        if metric is None:
            return
        metric.completed_at = time.perf_counter()
        metric.status = "failed"
        metric.error_message = error

    def skip_transformer(self, table_name: str) -> None:
        """Record a transformer skip (checkpoint resume)."""
        self.transformers[table_name] = TransformerMetric(
            table_name=table_name,
            started_at=time.perf_counter(),
            completed_at=time.perf_counter(),
            status="skipped",
        )

    def finalize(self) -> None:
        """Mark the pipeline run as complete."""
        self.completed_at = time.perf_counter()

    @property
    def total_duration(self) -> float:
        if self.completed_at is None:
            return time.perf_counter() - self.started_at
        return self.completed_at - self.started_at

    @property
    def success_count(self) -> int:
        return sum(1 for m in self.transformers.values() if m.status == "success")

    @property
    def failed_count(self) -> int:
        return sum(1 for m in self.transformers.values() if m.status == "failed")

    @property
    def skipped_count(self) -> int:
        return sum(1 for m in self.transformers.values() if m.status == "skipped")

    @property
    def total_rows(self) -> int:
        return sum(m.row_count for m in self.transformers.values())

    def slowest(self, n: int = 5) -> list[TransformerMetric]:
        """Return the N slowest successful transformers."""
        completed = [m for m in self.transformers.values() if m.status == "success"]
        return sorted(completed, key=lambda m: m.duration_seconds, reverse=True)[:n]

    def summary(self) -> dict:
        """Return a structured summary of the pipeline run."""
        return {
            "run_id": self.run_id,
            "total_duration_seconds": round(self.total_duration, 2),
            "transformers_total": len(self.transformers),
            "success": self.success_count,
            "failed": self.failed_count,
            "skipped": self.skipped_count,
            "total_rows": self.total_rows,
            "slowest_5": [
                {
                    "table": m.table_name,
                    "duration_seconds": round(m.duration_seconds, 2),
                    "rows": m.row_count,
                }
                for m in self.slowest(5)
            ],
            "failures": [
                {
                    "table": m.table_name,
                    "error": m.error_message,
                    "duration_seconds": round(m.duration_seconds, 2),
                }
                for m in self.transformers.values()
                if m.status == "failed"
            ],
        }

    def log_summary(self) -> None:
        """Log a human-readable summary."""
        s = self.summary()
        logger.info(
            "Pipeline metrics: {}/{} succeeded, {} failed, {} skipped in {:.1f}s ({:,} total rows)",
            s["success"],
            s["transformers_total"],
            s["failed"],
            s["skipped"],
            s["total_duration_seconds"],
            s["total_rows"],
        )
        if s["slowest_5"]:
            logger.info("Slowest transformers:")
            for item in s["slowest_5"]:
                logger.info(
                    "  {}: {:.2f}s ({:,} rows)",
                    item["table"],
                    item["duration_seconds"],
                    item["rows"],
                )
        if s["failures"]:
            logger.warning("Failed transformers:")
            for item in s["failures"]:
                logger.warning("  {}: {}", item["table"], item["error"])

    def persist(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Write all metrics to the _transform_metrics table."""
        now = datetime.now(UTC).isoformat()
        for metric in self.transformers.values():
            try:
                conn.execute(
                    """INSERT INTO _transform_metrics
                       (run_id, table_name, started_at, completed_at,
                        duration_seconds, row_count, column_count, status, error_message)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                       ON CONFLICT (run_id, table_name) DO UPDATE SET
                           completed_at = EXCLUDED.completed_at,
                           duration_seconds = EXCLUDED.duration_seconds,
                           row_count = EXCLUDED.row_count,
                           column_count = EXCLUDED.column_count,
                           status = EXCLUDED.status,
                           error_message = EXCLUDED.error_message""",
                    [
                        self.run_id,
                        metric.table_name,
                        now,
                        now if metric.completed_at else None,
                        metric.duration_seconds,
                        metric.row_count,
                        metric.column_count,
                        metric.status,
                        metric.error_message,
                    ],
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist metric for {}: {}",
                    metric.table_name,
                    type(exc).__name__,
                )
