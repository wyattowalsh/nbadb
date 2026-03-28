from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import polars as pl

from nbadb.transform.facts._detail_utils import empty_frame, typed_column

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class SingleMetricDetailSpec:
    staging_key: str
    metric_column: str | None = None
    variant: str | None = None


def consolidate_single_metric_family(
    staging: dict[str, pl.LazyFrame],
    *,
    specs: Sequence[SingleMetricDetailSpec],
    variant_column: str,
    output_schema: dict[str, Any],
    passthrough_columns: Sequence[str],
    value_column: str = "stat_value",
    sort_columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    frames: list[pl.DataFrame] = []
    excluded_columns = set(passthrough_columns)

    for spec in specs:
        frame = staging.get(spec.staging_key)
        if frame is None:
            continue

        df = cast("pl.DataFrame", frame.collect())
        if df.is_empty():
            continue

        metric_column = _resolve_metric_column(df, spec, excluded_columns)
        if metric_column is None:
            raise ValueError(
                f"{spec.staging_key}: unable to determine metric column from {df.columns}"
            )

        exprs = [pl.lit(spec.variant or metric_column).cast(pl.Utf8).alias(variant_column)]
        for column in passthrough_columns:
            exprs.append(typed_column(df, column, output_schema[column]))
        exprs.append(
            pl.col(metric_column)
            .cast(output_schema[value_column], strict=False)
            .alias(value_column)
        )
        frames.append(df.select(exprs))

    if not frames:
        return empty_frame(output_schema)

    result = pl.concat(frames, how="diagonal_relaxed").select(list(output_schema))
    order = [column for column in sort_columns or () if column in result.columns]
    return result.sort(order) if order else result


def _resolve_metric_column(
    df: pl.DataFrame,
    spec: SingleMetricDetailSpec,
    excluded_columns: set[str],
) -> str | None:
    if spec.metric_column is not None and spec.metric_column in df.columns:
        return spec.metric_column

    metric_columns = [column for column in df.columns if column not in excluded_columns]
    if len(metric_columns) == 1:
        return metric_columns[0]
    return None
