"""Tests for nbadb scan CLI command — CI integration flags."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import duckdb

from nbadb.cli.app import app
from nbadb.orchestrate.scanner import ScanFinding, ScanReport

if TYPE_CHECKING:
    from pathlib import Path


from typer.testing import CliRunner

runner = CliRunner()


def _make_db(path: Path) -> None:
    """Create a minimal DuckDB with dim_game so scan has something to read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    conn.execute("CREATE TABLE dim_game (game_id VARCHAR, game_date DATE, season_year VARCHAR)")
    conn.execute("INSERT INTO dim_game VALUES ('G1', '2024-10-22', '2024-25')")
    conn.close()


def _make_report(
    *,
    errors: int = 0,
    warnings: int = 0,
    infos: int = 0,
) -> ScanReport:
    """Build a ScanReport with the requested finding counts."""
    findings: list[ScanFinding] = []
    for i in range(errors):
        findings.append(
            ScanFinding(
                category="data_quality",
                severity="error",
                table=f"fact_err_{i}",
                check="null_key_column",
                message=f"Error finding {i}",
            )
        )
    for i in range(warnings):
        findings.append(
            ScanFinding(
                category="cross_table",
                severity="warning",
                table=f"fact_warn_{i}",
                check="game_coverage",
                message=f"Warning finding {i}",
            )
        )
    for i in range(infos):
        findings.append(
            ScanFinding(
                category="temporal",
                severity="info",
                table=f"fact_info_{i}",
                check="date_gap",
                message=f"Info finding {i}",
            )
        )
    return ScanReport(
        findings=findings,
        tables_scanned=5,
        checks_run=10,
        duration_seconds=1.5,
    )


def _patch_scanner(report: ScanReport):
    """Return a context manager that patches DataScanner.scan to return *report*."""

    class FakeScanner:
        def __init__(self, conn: object) -> None:
            pass

        def scan(self, **kwargs: object) -> ScanReport:
            return report

    return patch("nbadb.orchestrate.scanner.DataScanner", FakeScanner)


# ── --fail-on ──


class TestFailOn:
    def test_exits_1_on_errors(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report = _make_report(errors=2, warnings=1)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
        ):
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan", "--fail-on", "error"])

        assert result.exit_code == 1

    def test_exits_0_when_only_warnings(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report = _make_report(warnings=3)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
        ):
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan", "--fail-on", "error"])

        assert result.exit_code == 0

    def test_fail_on_warning_exits_1(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report = _make_report(warnings=1)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
        ):
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan", "--fail-on", "warning"])

        assert result.exit_code == 1

    def test_no_fail_on_always_exits_0(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report = _make_report(errors=5, warnings=3)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
        ):
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan"])

        assert result.exit_code == 0

    def test_fail_on_independent_of_severity_filter(self, tmp_path: Path) -> None:
        """--fail-on checks ALL findings, even if --severity hides some."""
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report = _make_report(errors=1, warnings=2, infos=3)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
        ):
            mock_settings.return_value.duckdb_path = db_path
            # --severity info filters out nothing; --fail-on error should still catch errors
            result = runner.invoke(app, ["scan", "--severity", "info", "--fail-on", "error"])

        assert result.exit_code == 1

    def test_fail_on_catches_hidden_warnings(self, tmp_path: Path) -> None:
        """--severity error hides warnings, but --fail-on warning still catches them."""
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report = _make_report(warnings=2)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
        ):
            mock_settings.return_value.duckdb_path = db_path
            # --severity error hides warnings from display,
            # but --fail-on warning should still exit 1
            result = runner.invoke(app, ["scan", "--severity", "error", "--fail-on", "warning"])

        assert result.exit_code == 1

    def test_invalid_fail_on_exits_1(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)

        with patch("nbadb.cli.commands.scan._build_settings") as mock_settings:
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan", "--fail-on", "critical"])

        assert result.exit_code == 1
        assert "Invalid --fail-on" in result.output


# ── --report-path ──


class TestReportPath:
    def test_creates_json_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report_file = tmp_path / "reports" / "scan.json"
        report = _make_report(errors=1, warnings=2)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
        ):
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan", "--report-path", str(report_file)])

        assert result.exit_code == 0
        assert report_file.exists()
        data = json.loads(report_file.read_text())
        assert "summary" in data
        assert "findings" in data
        assert data["summary"]["total"] == 3

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report_file = tmp_path / "deep" / "nested" / "dir" / "scan.json"
        report = _make_report()

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
        ):
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan", "--report-path", str(report_file)])

        assert result.exit_code == 0
        assert report_file.exists()


# ── --ci ──


class TestCiFlag:
    def test_writes_step_summary(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        summary_file = tmp_path / "step_summary.md"
        summary_file.write_text("")  # Create empty file
        report = _make_report(errors=1, warnings=1, infos=1)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
            patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary_file)}),
        ):
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan", "--ci"])

        assert result.exit_code == 0
        md = summary_file.read_text()
        assert "Data Scan Report" in md
        assert "Checks run" in md

    def test_emits_annotations(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report = _make_report(errors=1, warnings=1)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
            patch.dict("os.environ", {}, clear=False),
        ):
            # Remove GITHUB_STEP_SUMMARY to skip file write
            import os

            os.environ.pop("GITHUB_STEP_SUMMARY", None)
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan", "--ci"])

        assert result.exit_code == 0
        assert "::error::" in result.output
        assert "::warning::" in result.output

    def test_no_annotations_without_ci(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nbadb" / "nba.duckdb"
        _make_db(db_path)
        report = _make_report(errors=1)

        with (
            _patch_scanner(report),
            patch("nbadb.cli.commands.scan._build_settings") as mock_settings,
        ):
            mock_settings.return_value.duckdb_path = db_path
            result = runner.invoke(app, ["scan"])

        assert "::error::" not in result.output
