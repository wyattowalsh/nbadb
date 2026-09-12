from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl

_MAX_SIGNED_BIGINT = (1 << 63) - 1


def _stable_college_id(value: str) -> int:
    """Return a reproducible positive BIGINT for one exact college name."""

    identity = json.dumps(
        [value],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % _MAX_SIGNED_BIGINT + 1


class DimCollegeTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_college"
    depends_on: ClassVar[list[str]] = ["stg_player_college"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        pc = staging["stg_player_college"]
        colleges = pc.select("college_name").unique().drop_nulls().sort("college_name")
        colleges = colleges.with_columns(
            pl.col("college_name")
            .map_elements(_stable_college_id, return_dtype=pl.Int64)
            .alias("college_id")
        )

        result = colleges.select(
            pl.col("college_id").cast(pl.Int64),
            "college_name",
        ).collect()
        if result["college_id"].n_unique() != result.height:
            raise ValueError("deterministic college surrogate collision")
        return result
