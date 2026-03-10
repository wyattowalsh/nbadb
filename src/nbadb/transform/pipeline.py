from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import duckdb
    import polars as pl

    from nbadb.transform.base import BaseTransformer


@dataclass
class PipelineResult:
    """Captures pass/fail details from a pipeline run."""

    completed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    """List of (table_name, error_message) tuples for failed transformers."""
    skipped: list[str] = field(default_factory=list)
    """List of table names loaded from checkpoint (skipped re-computation)."""

    @property
    def success_count(self) -> int:
        return len(self.completed)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    @property
    def failed_tables(self) -> list[str]:
        return [t for t, _ in self.failed]


class TransformPipeline:
    def __init__(
        self,
        conn: duckdb.DuckDBPyConnection,
        *,
        run_id: str | None = None,
    ) -> None:
        self._conn = conn
        self._run_id = run_id or uuid.uuid4().hex
        self._transformers: list[BaseTransformer] = []
        self._outputs: dict[str, pl.DataFrame] = {}
        self._last_result: PipelineResult | None = None

    @property
    def last_result(self) -> PipelineResult | None:
        """Access the pass/fail summary from the most recent run."""
        return self._last_result

    def register(self, transformer: BaseTransformer) -> None:
        self._transformers.append(transformer)

    def register_all(self, transformers: list[BaseTransformer]) -> None:
        self._transformers.extend(transformers)

    # ------------------------------------------------------------------
    # Checkpoint persistence
    # ------------------------------------------------------------------

    def _save_checkpoint(self, table: str, row_count: int) -> None:
        """Record a completed table in the checkpoint table."""
        try:
            self._conn.execute(
                "INSERT INTO _transform_checkpoints (run_id, table_name, row_count) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT (run_id, table_name) DO UPDATE "
                "SET completed_at = now(), row_count = EXCLUDED.row_count",
                [self._run_id, table, row_count],
            )
        except Exception:
            logger.debug(f"Checkpoint save failed for '{table}' (non-fatal)")

    def _load_checkpoint(self) -> set[str]:
        """Return set of table names completed in a prior run with this run_id."""
        try:
            rows = self._conn.execute(
                "SELECT table_name FROM _transform_checkpoints WHERE run_id = ?",
                [self._run_id],
            ).fetchall()
            return {row[0] for row in rows}
        except Exception:
            return set()

    def _clear_checkpoint(self) -> None:
        """Remove all checkpoint entries for this run_id (clean completion)."""
        try:
            self._conn.execute(
                "DELETE FROM _transform_checkpoints WHERE run_id = ?",
                [self._run_id],
            )
        except Exception:
            logger.debug("Checkpoint clear failed (non-fatal)")

    # ------------------------------------------------------------------
    # Core pipeline logic
    # ------------------------------------------------------------------

    def _topological_sort(self) -> list[BaseTransformer]:
        graph: dict[str, BaseTransformer] = {t.output_table: t for t in self._transformers}
        white, gray, black = 0, 1, 2
        color: dict[str, int] = {name: white for name in graph}
        order: list[BaseTransformer] = []

        def visit(name: str) -> None:
            if name not in color or color[name] == black:
                return
            if color[name] == gray:
                raise ValueError(f"Cyclic dependency detected involving '{name}'")
            color[name] = gray
            transformer = graph.get(name)
            if transformer:
                for dep in transformer.depends_on:
                    visit(dep)
                order.append(transformer)
            color[name] = black

        for name in graph:
            visit(name)
        return order

    def _register_staging(self, staging: dict[str, pl.LazyFrame]) -> None:
        """Register all staging tables into the shared DuckDB connection once."""
        for key, val in staging.items():
            try:
                data = val.collect() if hasattr(val, "collect") else val
                self._conn.register(key, data)
            except Exception:
                logger.warning(f"Failed to register staging table '{key}'")

    def run(
        self,
        staging: dict[str, pl.LazyFrame],
        *,
        resume: bool = False,
    ) -> dict[str, pl.DataFrame]:
        ordered = self._topological_sort()
        logger.info(f"Pipeline: {len(ordered)} transformers in dependency order")

        result = PipelineResult()
        self._last_result = result

        # Load checkpoint data when resuming
        checkpointed: set[str] = set()
        if resume:
            checkpointed = self._load_checkpoint()
            if checkpointed:
                logger.info(f"Checkpoint: {len(checkpointed)} tables from prior run")

        # INFRA-006: Register all staging tables ONCE before the transformer loop
        self._register_staging(staging)

        try:
            for transformer in ordered:
                table = transformer.output_table

                # Resume path: skip if already in memory outputs
                if resume and table in self._outputs:
                    logger.info(f"Skipping {table} (already completed)")
                    result.completed.append(table)
                    continue

                # Checkpoint resume: skip if table was checkpointed and exists in DuckDB
                if resume and table in checkpointed:
                    try:
                        df = self._conn.execute(f'SELECT * FROM "{table}"').pl()
                        self._outputs[table] = df
                        result.completed.append(table)
                        result.skipped.append(table)
                        logger.info(f"Skipping {table} (loaded from checkpoint)")
                        continue
                    except Exception:
                        logger.warning(
                            f"Checkpoint entry for '{table}' but table not in DuckDB, re-computing"
                        )

                try:
                    transformer._conn = self._conn
                    # Build combined view: original staging + accumulated outputs
                    combined = {**staging}
                    for name, out_df in self._outputs.items():
                        combined[name] = out_df.lazy()
                    df = transformer.run(combined)
                except Exception as exc:
                    tb = traceback.format_exc()
                    error_msg = f"{type(exc).__name__}: {exc}"
                    logger.error(
                        f"Transformer '{table}' failed "
                        f"({type(transformer).__name__}, "
                        f"depends_on={transformer.depends_on}, "
                        f"completed={result.success_count}/{len(ordered)}): "
                        f"{error_msg}\n{tb}"
                    )
                    result.failed.append((table, error_msg))
                    continue
                self._outputs[table] = df
                # INFRA-006: Only register the NEW output from each completed transformer
                self._conn.register(table, df)
                result.completed.append(table)
                self._save_checkpoint(table, df.shape[0])
                logger.debug(f"Registered {table} in DuckDB ({df.shape[0]} rows)")

            # QUAL-005: Log summary of pass/fail counts
            logger.info(
                f"Pipeline finished: {result.success_count} passed, "
                f"{result.failure_count} failed out of {len(ordered)} transformers"
            )
            if result.failed:
                logger.warning(f"Failed transformers: {result.failed_tables}")

            # Clean run completed — clear checkpoint data
            if not result.failed:
                self._clear_checkpoint()
        finally:
            for t in self._transformers:
                t._conn = None

        return self._outputs

    def get_output(self, table: str) -> pl.DataFrame | None:
        return self._outputs.get(table)

    @property
    def execution_order(self) -> list[str]:
        return [t.output_table for t in self._topological_sort()]
