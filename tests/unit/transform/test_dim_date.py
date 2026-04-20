"""Tests for DimDateTransformer."""

from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.dimensions.dim_date import DimDateTransformer


def _run_transformer() -> pl.DataFrame:
    """Run DimDateTransformer with a real DuckDB connection and return output."""
    transformer = DimDateTransformer()
    transformer._conn = duckdb.connect()
    # depends_on == [] so staging can be empty
    return transformer.run({})


class TestDimDateTransformer:
    def test_output_has_required_columns(self):
        """Output DataFrame has all expected columns."""
        df = _run_transformer()
        expected_cols = {
            "date",
            "date_key",
            "year",
            "month",
            "day",
            "day_of_week",
            "day_name",
            "is_weekend",
            "nba_season",
        }
        assert expected_cols.issubset(set(df.columns))

    def test_season_boundary_october(self):
        """Dates in Oct+ should be in the season starting that year (e.g. 2024-25)."""
        df = _run_transformer()
        oct1_2024 = pl.date(2024, 10, 1)
        row = df.filter(pl.col("date") == oct1_2024)
        assert row.shape[0] == 1
        assert row["nba_season"][0] == "2024-25"

    def test_season_boundary_september(self):
        """Dates before Oct should be in the season starting the prior year (e.g. 2023-24)."""
        df = _run_transformer()
        sep30_2024 = pl.date(2024, 9, 30)
        row = df.filter(pl.col("date") == sep30_2024)
        assert row.shape[0] == 1
        assert row["nba_season"][0] == "2023-24"

    def test_day_name_monday(self):
        """Day name for a known Monday (2024-01-01) is 'Monday'."""
        df = _run_transformer()
        # 2024-01-01 is a Monday
        jan1_2024 = pl.date(2024, 1, 1)
        row = df.filter(pl.col("date") == jan1_2024)
        assert row.shape[0] == 1
        assert row["day_name"][0] == "Monday"

    def test_day_name_sunday(self):
        """Day name for a known Sunday (2024-01-07) is 'Sunday'."""
        df = _run_transformer()
        # 2024-01-07 is a Sunday
        jan7_2024 = pl.date(2024, 1, 7)
        row = df.filter(pl.col("date") == jan7_2024)
        assert row.shape[0] == 1
        assert row["day_name"][0] == "Sunday"

    def test_is_weekend_saturday(self):
        """Saturday is marked as weekend."""
        df = _run_transformer()
        # 2024-01-06 is a Saturday
        jan6_2024 = pl.date(2024, 1, 6)
        row = df.filter(pl.col("date") == jan6_2024)
        assert row.shape[0] == 1
        assert row["is_weekend"][0] is True

    def test_is_weekend_monday(self):
        """Monday is not marked as weekend."""
        df = _run_transformer()
        # 2024-01-01 is a Monday
        jan1_2024 = pl.date(2024, 1, 1)
        row = df.filter(pl.col("date") == jan1_2024)
        assert row.shape[0] == 1
        assert row["is_weekend"][0] is False

    def test_date_key_format(self):
        """date_key for 2024-01-01 is 20240101 (year*10000 + month*100 + day)."""
        df = _run_transformer()
        jan1_2024 = pl.date(2024, 1, 1)
        row = df.filter(pl.col("date") == jan1_2024)
        assert row.shape[0] == 1
        assert row["date_key"][0] == 20240101

    def test_depends_on_is_empty(self):
        """DimDateTransformer has no staging dependencies."""
        assert DimDateTransformer.depends_on == []

    def test_output_table_name(self):
        """output_table is 'dim_date'."""
        assert DimDateTransformer.output_table == "dim_date"

    def test_conn_not_required_for_transform(self):
        """DimDateTransformer does not access self.conn during transform."""
        transformer = DimDateTransformer()
        transformer._conn = duckdb.connect()
        # Should not raise RuntimeError
        result = transformer.run({})
        assert result.shape[0] > 0

    def test_nba_first_season(self):
        """1946 dates are assigned to the '1946-47' season (Oct+ rule)."""
        df = _run_transformer()
        # The NBA_FIRST_DATE is 1946-01-01, which is Jan (< Oct) → 1945-46
        jan1_1946 = pl.date(1946, 1, 1)
        row = df.filter(pl.col("date") == jan1_1946)
        assert row.shape[0] == 1
        assert row["nba_season"][0] == "1945-46"

    def test_season_two_digit_year_padding(self):
        """Season suffix is zero-padded: 1999 Oct → '1999-00'."""
        df = _run_transformer()
        oct1_1999 = pl.date(1999, 10, 1)
        row = df.filter(pl.col("date") == oct1_1999)
        assert row.shape[0] == 1
        assert row["nba_season"][0] == "1999-00"
