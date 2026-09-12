from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
from polars.testing import assert_frame_equal

if TYPE_CHECKING:
    from pathlib import Path


def test_nested_arrow_duckdb_parquet_round_trip(tmp_path: Path) -> None:
    """Exercise the typed interchange path used by authoritative columnar exports."""
    base = pl.DataFrame(
        {
            "row_id": pl.Series([0, 1, 2, 3, 4], dtype=pl.Int64),
            "nested_list": pl.Series(
                [[99], [], None, [3, None, 5], [88]],
                dtype=pl.List(pl.Int64),
            ),
            "nested_struct": pl.Series(
                [
                    {"label": "drop", "score": Decimal("9.99")},
                    {"label": "empty", "score": Decimal("1.20")},
                    None,
                    {"label": None, "score": Decimal("-3.40")},
                    {"label": "drop", "score": Decimal("8.88")},
                ],
                dtype=pl.Struct(
                    {
                        "label": pl.String,
                        "score": pl.Decimal(precision=10, scale=2),
                    }
                ),
            ),
            "category": pl.Series(
                ["drop", "home", None, "away", "drop"],
                dtype=pl.Categorical,
            ),
            "nullable_bool": pl.Series(
                [False, True, None, False, True],
                dtype=pl.Boolean,
            ),
            "game_date": pl.Series(
                [date(2024, 1, 1), date(2024, 1, 2), None, date(2024, 1, 4), date(2024, 1, 5)],
                dtype=pl.Date,
            ),
            "tipoff_utc": pl.Series(
                [
                    datetime(2024, 1, 1, tzinfo=UTC),
                    datetime(2024, 1, 2, 3, 4, 5, 123456, tzinfo=UTC),
                    None,
                    datetime(2024, 1, 4, 5, 6, 7, tzinfo=UTC),
                    datetime(2024, 1, 5, tzinfo=UTC),
                ],
                dtype=pl.Datetime(time_unit="us", time_zone="UTC"),
            ),
            "amount": pl.Series(
                [Decimal("9.99"), Decimal("1.20"), None, Decimal("-3.40"), Decimal("8.88")],
                dtype=pl.Decimal(precision=12, scale=2),
            ),
            "text": pl.Series(["drop", "", None, "value", "drop"], dtype=pl.String),
        }
    )

    # Keep non-zero Arrow offsets in the interchange input instead of testing only
    # freshly allocated, zero-offset arrays.
    sliced = base.slice(1, 3)
    arrow_input = sliced.to_arrow()
    assert arrow_input.column("row_id").chunk(0).offset == 1
    assert pa.types.is_dictionary(arrow_input.schema.field("category").type)

    parquet_path = tmp_path / "arrow-interop.parquet"
    connection = duckdb.connect()
    try:
        connection.register("_arrow_interop", arrow_input)
        connection.execute("CREATE TABLE arrow_interop AS SELECT * FROM _arrow_interop")
        connection.execute(
            "COPY arrow_interop TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
            [str(parquet_path)],
        )
    finally:
        connection.close()

    polars_output = pl.read_parquet(parquet_path)
    arrow_output = pq.read_table(parquet_path)

    # DuckDB deliberately materializes Arrow dictionaries as VARCHAR; values and
    # nulls must remain exact across that documented physical normalization.
    expected = sliced.with_columns(pl.col("category").cast(pl.String))
    assert_frame_equal(polars_output, expected)
    assert arrow_output.to_pylist() == expected.to_arrow().to_pylist()

    schema = arrow_output.schema
    assert pa.types.is_list(schema.field("nested_list").type)
    assert pa.types.is_struct(schema.field("nested_struct").type)
    assert pa.types.is_boolean(schema.field("nullable_bool").type)
    assert pa.types.is_date32(schema.field("game_date").type)
    assert pa.types.is_timestamp(schema.field("tipoff_utc").type)
    assert schema.field("tipoff_utc").type.tz == "UTC"
    assert pa.types.is_decimal128(schema.field("amount").type)
    assert schema.field("amount").type.precision == 12
    assert schema.field("amount").type.scale == 2

    rows = arrow_output.to_pylist()
    assert rows[0]["nested_list"] == []
    assert rows[1]["nested_list"] is None
    assert rows[0]["text"] == ""
    assert rows[1]["text"] is None
