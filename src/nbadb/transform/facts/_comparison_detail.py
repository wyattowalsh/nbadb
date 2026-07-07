from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from nbadb.transform.facts._detail_utils import empty_frame, typed_column

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class ComparisonDetailSpec:
    staging_key: str
    labels: Mapping[str, str]


def consolidate_detail_family(
    staging: dict[str, pl.LazyFrame],
    *,
    specs: Sequence[ComparisonDetailSpec],
    output_schema: dict[str, Any],
    passthrough_columns: Sequence[str],
    sort_columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []

    for spec in specs:
        frame = staging.get(spec.staging_key)
        if frame is None:
            continue

        df = cast("pl.DataFrame", frame.collect())
        if df.is_empty():
            continue

        exprs = [
            pl.lit(value).cast(output_schema[column], strict=False).alias(column)
            for column, value in spec.labels.items()
        ]
        for column in passthrough_columns:
            exprs.append(typed_column(df, column, output_schema[column]))
        frames.append(df.select(exprs))

    if not frames:
        return empty_frame(output_schema)

    result = pl.concat(frames, how="diagonal_relaxed").select(list(output_schema))
    order = [column for column in sort_columns or () if column in result.columns]
    return result.sort(order) if order else result
