"""Tests for nbadb.kaggle.notebook — update mode, summary, row validation."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from nbadb.kaggle.notebook import determine_update_mode, print_summary, validate_row_counts


class TestDetermineUpdateMode:
    def test_monthly_on_day_1(self) -> None:
        with patch("nbadb.kaggle.notebook.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 3, 1)
            assert determine_update_mode() == "monthly"

    def test_monthly_on_day_7(self) -> None:
        with patch("nbadb.kaggle.notebook.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 3, 7)
            assert determine_update_mode() == "monthly"

    def test_monthly_on_day_3(self) -> None:
        with patch("nbadb.kaggle.notebook.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 6, 3)
            assert determine_update_mode() == "monthly"

    def test_daily_on_day_8(self) -> None:
        with patch("nbadb.kaggle.notebook.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 3, 8)
            assert determine_update_mode() == "daily"

    def test_daily_on_day_15(self) -> None:
        with patch("nbadb.kaggle.notebook.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 3, 15)
            assert determine_update_mode() == "daily"

    def test_daily_on_day_28(self) -> None:
        with patch("nbadb.kaggle.notebook.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 28)
            assert determine_update_mode() == "daily"

    def test_daily_on_day_31(self) -> None:
        with patch("nbadb.kaggle.notebook.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 31)
            assert determine_update_mode() == "daily"


class TestPrintSummary:
    def test_logs_without_error(self) -> None:
        # Should not raise
        print_summary("daily", tables_updated=10, rows_total=5000, duration_seconds=42.3)

    def test_monthly_mode(self) -> None:
        print_summary("monthly", tables_updated=50, rows_total=100_000, duration_seconds=300.0)

    def test_zero_values(self) -> None:
        print_summary("full", tables_updated=0, rows_total=0, duration_seconds=0.0)


class TestValidateRowCounts:
    def test_empty_expected(self) -> None:
        assert validate_row_counts({}, {}) == []

    def test_within_tolerance(self) -> None:
        expected = {"games": 100}
        actual = {"games": 98}
        assert validate_row_counts(expected, actual) == []

    def test_exactly_at_tolerance(self) -> None:
        expected = {"games": 100}
        actual = {"games": 95}  # 5% diff == 5% tolerance
        assert validate_row_counts(expected, actual) == []

    def test_exceeds_tolerance(self) -> None:
        expected = {"games": 100}
        actual = {"games": 50}
        warnings = validate_row_counts(expected, actual)
        assert len(warnings) == 1
        assert "games" in warnings[0]

    def test_missing_table_in_actual(self) -> None:
        expected = {"games": 100}
        actual = {}
        warnings = validate_row_counts(expected, actual)
        assert len(warnings) == 1
        assert "games" in warnings[0]

    def test_zero_expected_skipped(self) -> None:
        expected = {"games": 0}
        actual = {"games": 100}
        assert validate_row_counts(expected, actual) == []

    def test_custom_tolerance_exceeds(self) -> None:
        expected = {"games": 100}
        actual = {"games": 85}
        # 15% diff > 10% tolerance
        warnings = validate_row_counts(expected, actual, tolerance=0.10)
        assert len(warnings) == 1

    def test_custom_tolerance_within(self) -> None:
        expected = {"games": 100}
        actual = {"games": 85}
        # 15% diff < 20% tolerance
        assert validate_row_counts(expected, actual, tolerance=0.20) == []

    def test_multiple_tables(self) -> None:
        expected = {"games": 100, "players": 500, "teams": 30}
        actual = {"games": 50, "players": 498, "teams": 29}
        warnings = validate_row_counts(expected, actual)
        # Only games should trigger (50% diff)
        assert len(warnings) == 1
        assert "games" in warnings[0]

    def test_extra_table_in_actual_ignored(self) -> None:
        expected = {"games": 100}
        actual = {"games": 100, "extra": 999}
        assert validate_row_counts(expected, actual) == []

    def test_warning_message_format(self) -> None:
        expected = {"stats": 1000}
        actual = {"stats": 500}
        warnings = validate_row_counts(expected, actual)
        assert len(warnings) == 1
        # Check the warning contains key info
        assert "stats" in warnings[0]
        assert "1,000" in warnings[0]
        assert "500" in warnings[0]
