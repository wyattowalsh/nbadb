from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import duckdb
    import polars as pl

    from nbadb.transform.base import BaseTransformer


class TransformPipeline:
    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn
        self._transformers: list[BaseTransformer] = []
        self._outputs: dict[str, pl.DataFrame] = {}

    def register(self, transformer: BaseTransformer) -> None:
        self._transformers.append(transformer)

    def register_all(self, transformers: list[BaseTransformer]) -> None:
        self._transformers.extend(transformers)

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

    def run(
        self,
        staging: dict[str, pl.LazyFrame],
        *,
        resume: bool = False,
    ) -> dict[str, pl.DataFrame]:
        ordered = self._topological_sort()
        logger.info(f"Pipeline: {len(ordered)} transformers in dependency order")
        completed: set[str] = set()
        failed_tables: list[str] = []
        try:
            for transformer in ordered:
                table = transformer.output_table
                if resume and table in self._outputs:
                    logger.info(f"Skipping {table} (already completed)")
                    completed.add(table)
                    continue
                combined = {**staging}
                for name, df in self._outputs.items():
                    combined[name] = df.lazy()
                try:
                    transformer._conn = self._conn
                    # Register all combined tables into shared conn for this transformer
                    for key, val in combined.items():
                        try:
                            data = val.collect() if hasattr(val, "collect") else val
                            self._conn.register(key, data)
                        except Exception:
                            pass
                    df = transformer.run(combined)
                except Exception:
                    logger.error(
                        f"Pipeline failed at {table} "
                        f"(transformer: {type(transformer).__name__}, "
                        f"depends_on: {transformer.depends_on}, "
                        f"completed: {len(completed)}/{len(ordered)})"
                    )
                    failed_tables.append(table)
                    continue
                self._outputs[table] = df
                self._conn.register(table, df)
                completed.add(table)
                logger.debug(f"Registered {table} in DuckDB ({df.shape[0]} rows)")

            if failed_tables:
                logger.warning(
                    f"Pipeline completed with {len(failed_tables)} failed "
                    f"transformers: {failed_tables}"
                )
        finally:
            for t in self._transformers:
                t._conn = None
        return self._outputs

    def get_output(self, table: str) -> pl.DataFrame | None:
        return self._outputs.get(table)

    @property
    def execution_order(self) -> list[str]:
        return [t.output_table for t in self._topological_sort()]
