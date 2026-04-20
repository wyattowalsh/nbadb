from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl

_PHASES: list[tuple[int, str]] = [
    (1, "Preseason"),
    (2, "Regular"),
    (3, "Play-In"),
    (4, "Playoffs R1"),
    (5, "Playoffs R2"),
    (6, "Conference Finals"),
    (7, "Finals"),
    (8, "All-Star"),
]


class DimSeasonPhaseTransformer(BaseTransformer):
    # NOTE: standalone lookup table — no FK refs in current star schema.
    # Kept as a reference dimension for downstream consumers that may
    # join on phase_id (e.g. ad-hoc queries, Kaggle exports).
    output_table: ClassVar[str] = "dim_season_phase"
    depends_on: ClassVar[list[str]] = []

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        return pl.DataFrame(
            {
                "phase_id": [p[0] for p in _PHASES],
                "phase_name": [p[1] for p in _PHASES],
                "phase_order": [p[0] for p in _PHASES],
            },
            schema={
                "phase_id": pl.Int32,
                "phase_name": pl.Utf8,
                "phase_order": pl.Int32,
            },
        )
