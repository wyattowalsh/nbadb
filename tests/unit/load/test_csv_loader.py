from __future__ import annotations

import csv
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import polars as pl
import pytest

from nbadb.kaggle.raw_value_codec import RawValueCodecError, decode_raw_value
from nbadb.load.csv_loader import CSVLoader, _project_raw_authority_convenience_frame
from nbadb.orchestrate.raw_request_store import RAW_REQUEST_AUTHORITY_TABLES

if TYPE_CHECKING:
    from pathlib import Path


_CONVENIENCE_COLUMNS = ("binary_value", "text_value", "null_value")


def _raw_native_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ordinal": pl.Series([0, 1, 2], dtype=pl.Int64),
            "binary_value": pl.Series([None, b"", b"\x00\xff"], dtype=pl.Binary),
            "text_value": pl.Series([None, "", "Ω"], dtype=pl.String),
            "null_value": pl.Series([None, None, None], dtype=pl.Null),
            "observed_at": pl.Series(
                [
                    datetime(2026, 8, 27, 1, 2, 3, 456789, tzinfo=UTC),
                    datetime(2026, 8, 28, tzinfo=UTC),
                    datetime(2026, 8, 29, 23, 59, 59, tzinfo=UTC),
                ],
                dtype=pl.Datetime("us", "UTC"),
            ),
        }
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class TestCSVLoader:
    def test_writes_csv_file(self, tmp_path: Path) -> None:
        loader = CSVLoader(tmp_path / "csv")
        df = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        loader.load("test_table", df)
        output = tmp_path / "csv" / "test_table.csv"
        assert output.exists()
        loaded = pl.read_csv(output)
        assert loaded.shape == (2, 2)
        assert loaded["a"].to_list() == [1, 2]

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        loader = CSVLoader(nested)
        df = pl.DataFrame({"x": [1]})
        loader.load("tbl", df)
        assert (nested / "tbl.csv").exists()

    def test_replace_overwrites(self, tmp_path: Path) -> None:
        loader = CSVLoader(tmp_path)
        df1 = pl.DataFrame({"v": [1, 2, 3]})
        df2 = pl.DataFrame({"v": [10]})
        loader.load("t", df1)
        loader.load("t", df2, mode="replace")
        loaded = pl.read_csv(tmp_path / "t.csv")
        assert loaded.shape == (1, 1)

    def test_append_raises_not_implemented(self, tmp_path: Path) -> None:
        """CSVLoader does not support append mode."""
        loader = CSVLoader(tmp_path)
        df = pl.DataFrame({"v": [1]})
        with pytest.raises(NotImplementedError, match="append mode not supported"):
            loader.load("t", df, mode="append")

    def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """Table names with path separators are rejected."""
        loader = CSVLoader(tmp_path)
        df = pl.DataFrame({"v": [1]})
        # validate_sql_identifier fires first for names with special chars
        with pytest.raises(ValueError):
            loader.load("../evil", df)
        with pytest.raises(ValueError):
            loader.load("sub/table", df)
        with pytest.raises(ValueError):
            loader.load("sub\\table", df)

    @pytest.mark.parametrize("table", RAW_REQUEST_AUTHORITY_TABLES)
    def test_fixed_raw_tables_have_exact_decoded_convenience_parity(
        self,
        tmp_path: Path,
        table: str,
    ) -> None:
        native = _raw_native_frame()
        loader = CSVLoader(tmp_path)

        loader.load(table, native)

        output = tmp_path / f"{table}.csv"
        rows = _read_csv_rows(output)
        for column_name in _CONVENIENCE_COLUMNS:
            decoded = [decode_raw_value(row[column_name]) for row in rows]
            expected = native[column_name].to_list()
            assert decoded == expected
            assert [type(value) for value in decoded] == [type(value) for value in expected]
        loaded = pl.read_csv(output, try_parse_dates=True)
        assert loaded["ordinal"].equals(native["ordinal"])
        assert loaded["observed_at"].equals(native["observed_at"])

    def test_raw_projection_leaves_numeric_and_datetime_series_native(self) -> None:
        native = _raw_native_frame()

        projected = _project_raw_authority_convenience_frame(
            RAW_REQUEST_AUTHORITY_TABLES[0],
            native,
        )

        assert all(projected.schema[column] == pl.String for column in _CONVENIENCE_COLUMNS)
        assert projected["ordinal"].equals(native["ordinal"])
        assert projected["observed_at"].equals(native["observed_at"])

    def test_empty_raw_frame_preserves_rows_columns_and_native_dtypes(self) -> None:
        native = pl.DataFrame(
            schema={
                "binary_value": pl.Binary,
                "text_value": pl.String,
                "null_value": pl.Null,
                "ordinal": pl.Int64,
                "observed_at": pl.Datetime("us", "UTC"),
            }
        )

        projected = _project_raw_authority_convenience_frame(
            RAW_REQUEST_AUTHORITY_TABLES[0],
            native,
        )

        assert projected.shape == native.shape
        assert projected.columns == native.columns
        assert all(projected.schema[column] == pl.String for column in _CONVENIENCE_COLUMNS)
        assert projected.schema["ordinal"] == native.schema["ordinal"]
        assert projected.schema["observed_at"] == native.schema["observed_at"]

    def test_nonfixed_raw_lookalike_preserves_plain_string_behavior(self, tmp_path: Path) -> None:
        loader = CSVLoader(tmp_path)
        loader.load(
            "raw_nba_api_shadow",
            pl.DataFrame({"value": pl.Series(["plain", ""], dtype=pl.String)}),
        )

        rows = _read_csv_rows(tmp_path / "raw_nba_api_shadow.csv")
        assert [row["value"] for row in rows] == ["plain", ""]

    def test_malformed_csv_convenience_value_fails_decoded_readback(self, tmp_path: Path) -> None:
        table = RAW_REQUEST_AUTHORITY_TABLES[0]
        loader = CSVLoader(tmp_path)
        loader.load(table, _raw_native_frame())
        encoded = _read_csv_rows(tmp_path / f"{table}.csv")[2]["binary_value"]

        with pytest.raises(RawValueCodecError):
            decode_raw_value(encoded[:-1])
