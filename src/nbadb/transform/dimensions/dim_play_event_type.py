from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl

_EVENT_TYPES: list[tuple[int, str]] = [
    (1, "made_shot"),
    (2, "missed_shot"),
    (3, "free_throw"),
    (4, "rebound"),
    (5, "turnover"),
    (6, "foul"),
    (7, "violation"),
    (8, "substitution"),
    (9, "timeout"),
    (10, "jump_ball"),
    (11, "ejection"),
    (12, "period_start"),
    (13, "period_end"),
    (14, "unknown"),
]


class DimPlayEventTypeTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_play_event_type"
    depends_on: ClassVar[list[str]] = []

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        import polars as pl

        return pl.DataFrame(
            {
                "event_type_id": [e[0] for e in _EVENT_TYPES],
                "event_type_name": [e[1] for e in _EVENT_TYPES],
            },
            schema={
                "event_type_id": pl.Int32,
                "event_type_name": pl.Utf8,
            },
        )
