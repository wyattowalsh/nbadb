from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

from loguru import logger

if TYPE_CHECKING:
    import duckdb
    import polars as pl


class BaseTransformer(ABC):
    output_table: ClassVar[str]
    depends_on: ClassVar[list[str]] = []

    def __init__(self) -> None:
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """Shared DuckDB connection injected by TransformPipeline."""
        if self._conn is None:
            raise RuntimeError(
                "No DuckDB connection injected. Use TransformPipeline.run() "
                "to execute transforms — do not call transformer.run() directly."
            )
        return self._conn

    @abstractmethod
    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame: ...

    def run(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        logger.info(f"Transforming {self.output_table}")
        df = self.transform(staging)
        logger.info(f"{self.output_table}: {df.shape[0]} rows, {df.shape[1]} cols")
        return df


class SqlTransformer(BaseTransformer):
    """Base for transformers that execute a single SQL query.

    Define ``_SQL`` as a ClassVar and the ``transform`` method is provided
    automatically.  There is no need to override ``transform()``.
    """

    _SQL: ClassVar[str] = ""

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        if not self._SQL:
            raise NotImplementedError(
                f"{type(self).__name__} must define a non-empty _SQL ClassVar"
            )
        return self.conn.execute(self._SQL).pl()


def _validate_identifier(name: str) -> None:
    """Validate that a name is a safe SQL identifier."""
    from nbadb.core.types import validate_sql_identifier

    validate_sql_identifier(name)


def make_passthrough(output_table: str, source_table: str) -> type[SqlTransformer]:
    """Create a SqlTransformer that passes through a staging table unchanged."""
    _validate_identifier(output_table)
    _validate_identifier(source_table)
    return type(
        f"{''.join(w.title() for w in output_table.split('_'))}Transformer",
        (SqlTransformer,),
        {
            "output_table": output_table,
            "depends_on": [source_table],
            "_SQL": f"SELECT * FROM {source_table}",
        },
    )


def make_union(
    output_table: str,
    discriminator: str,
    branches: dict[str, str],
) -> type[SqlTransformer]:
    """Create a SqlTransformer that UNIONs staging tables with a discriminator column."""
    _validate_identifier(output_table)
    _validate_identifier(discriminator)
    parts = []
    depends = []
    for label, stg_table in branches.items():
        _validate_identifier(stg_table)
        parts.append(f"SELECT *, '{label}' AS {discriminator} FROM {stg_table}")
        depends.append(stg_table)
    sql = "\nUNION ALL BY NAME\n".join(parts)
    return type(
        f"{''.join(w.title() for w in output_table.split('_'))}Transformer",
        (SqlTransformer,),
        {
            "output_table": output_table,
            "depends_on": depends,
            "_SQL": sql,
        },
    )
