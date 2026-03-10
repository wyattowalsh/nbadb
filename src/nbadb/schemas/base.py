from __future__ import annotations

from typing import Any

import pandera.polars as pa
from loguru import logger


class BaseSchema(pa.DataFrameModel):
    """Two-tier validation schema.

    - Hard-fail on missing required columns and wrong data types.
    - Soft-warn and strip unexpected extra columns.

    Uses ``strict=False`` so pandera does not reject extra columns outright,
    then explicitly drops them after logging a warning.
    """

    class Config:
        coerce = True
        strict = False

    @classmethod
    def validate(  # type: ignore[override]
        cls,
        data: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        import polars as pl

        # Determine the required columns declared in this schema
        schema_obj = cls.to_schema()
        expected_columns: set[str] = set(schema_obj.columns)

        # Detect extra columns present in the data but not in the schema
        if isinstance(data, (pl.DataFrame, pl.LazyFrame)):
            if isinstance(data, pl.LazyFrame):
                actual_columns = set(data.collect_schema().names())
            else:
                actual_columns = set(data.columns)

            extra = sorted(actual_columns - expected_columns)
            if extra:
                logger.warning(
                    f"{cls.__name__}: stripping {len(extra)} unexpected column(s): {extra}"
                )
                data = data.drop(extra)

        # Pandera validates required columns + types (hard-fail)
        return super().validate(data, *args, **kwargs)
