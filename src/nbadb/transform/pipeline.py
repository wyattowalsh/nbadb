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
        visited: set[str] = set()
        order: list[BaseTransformer] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            transformer = graph.get(name)
            if transformer is None:
                return
            for dep in transformer.depends_on:
                visit(dep)
            order.append(transformer)

        for name in graph:
            visit(name)
        return order

    def run(self, staging: dict[str, pl.LazyFrame]) -> dict[str, pl.DataFrame]:
        ordered = self._topological_sort()
        logger.info(f"Pipeline: {len(ordered)} transformers in dependency order")
        for transformer in ordered:
            combined = {**staging}
            for name, df in self._outputs.items():
                combined[name] = df.lazy()
            df = transformer.run(combined)
            self._outputs[transformer.output_table] = df
            self._conn.register(transformer.output_table, df)
            logger.debug(f"Registered {transformer.output_table} in DuckDB ({df.shape[0]} rows)")
        return self._outputs

    def get_output(self, table: str) -> pl.DataFrame | None:
        return self._outputs.get(table)

    @property
    def execution_order(self) -> list[str]:
        return [t.output_table for t in self._topological_sort()]
