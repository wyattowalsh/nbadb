from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings, _open_db_readonly
from nbadb.cli.options import DataDirOption  # noqa: TC001
from nbadb.orchestrate.scanner import ScanCategory, ScanSeverity

_VALID_CATEGORIES = {c.value for c in ScanCategory}
_VALID_SEVERITIES = {s.value for s in ScanSeverity}
_SEVERITY_ORDER = {s.value: i for i, s in enumerate(ScanSeverity)}


@app.command()
def scan(
    data_dir: DataDirOption = None,
    category: Annotated[
        str | None,
        typer.Option(
            "--category",
            "-c",
            help="Comma-separated categories: cross_table,temporal,missing_table,data_quality",
        ),
    ] = None,
    table: Annotated[
        str | None,
        typer.Option(
            "--table",
            "-t",
            help="Filter by table name prefix (e.g. 'fact_box_score', 'stg_', 'dim_')",
        ),
    ] = None,
    severity: Annotated[
        str | None,
        typer.Option(
            "--severity",
            "-s",
            help="Minimum severity to show: error, warning, info",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--output-format", "-f", help="Output format: text or json"),
    ] = "text",
    fail_on: Annotated[
        str | None,
        typer.Option(
            "--fail-on",
            "-F",
            help="Exit 1 if findings at or above this severity: error, warning, info",
        ),
    ] = None,
    report_path: Annotated[
        str | None,
        typer.Option(
            "--report-path",
            "-r",
            help="Write JSON report to this file path",
        ),
    ] = None,
    ci: Annotated[
        bool,
        typer.Option(
            "--ci",
            help="Enable GitHub Actions integration (step summary + annotations)",
        ),
    ] = False,
) -> None:
    """Scan the database for missing data, gaps, and quality issues."""
    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path

    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.", err=True)
        raise typer.Exit(1)

    # Validate --fail-on
    if fail_on and fail_on not in _VALID_SEVERITIES:
        typer.echo(
            f"Invalid --fail-on severity: {fail_on}. Valid: {', '.join(sorted(_VALID_SEVERITIES))}",
            err=True,
        )
        raise typer.Exit(1)

    # Parse and validate category filter
    categories: list[str] | None = None
    if category:
        categories = [c.strip() for c in category.split(",")]
        invalid = set(categories) - _VALID_CATEGORIES
        if invalid:
            typer.echo(
                f"Invalid categories: {', '.join(invalid)}. "
                f"Valid: {', '.join(sorted(_VALID_CATEGORIES))}",
                err=True,
            )
            raise typer.Exit(1)

    if severity and severity not in _VALID_SEVERITIES:
        typer.echo(
            f"Invalid severity: {severity}. Valid: {', '.join(sorted(_VALID_SEVERITIES))}",
            err=True,
        )
        raise typer.Exit(1)

    from nbadb.orchestrate.scanner import DataScanner

    conn = _open_db_readonly(db_path)
    try:
        scanner = DataScanner(conn)
        report = scanner.scan(categories=categories, table_filter=table)

        # Apply severity filter for display
        findings = report.findings
        if severity:
            max_level = _SEVERITY_ORDER.get(severity, 2)
            findings = [f for f in findings if _SEVERITY_ORDER.get(f.severity, 2) <= max_level]

        # ── Output ──
        if output_format == "json":
            data = {
                "summary": {
                    "total": len(findings),
                    "error": sum(1 for f in findings if f.severity == "error"),
                    "warning": sum(1 for f in findings if f.severity == "warning"),
                    "info": sum(1 for f in findings if f.severity == "info"),
                    "tables_scanned": report.tables_scanned,
                    "checks_run": report.checks_run,
                },
                "duration_seconds": report.duration_seconds,
                "findings": [
                    {
                        "category": f.category,
                        "severity": f.severity,
                        "table": f.table,
                        "check": f.check,
                        "message": f.message,
                        "details": f.details,
                    }
                    for f in findings
                ],
            }
            typer.echo(json.dumps(data, indent=2, default=str))
        else:
            _print_scan_report(report, findings)

        # ── Write JSON report file (always unfiltered by --severity) ──
        if report_path:
            out = Path(report_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(report.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            typer.echo(f"Report written to {out}", err=True)

        # ── GitHub Actions integration ──
        if ci:
            # Step summary
            summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
            if summary_path:
                with open(summary_path, "a", encoding="utf-8") as fh:
                    fh.write(report.to_markdown())
                    fh.write("\n")

            # Annotations
            for line in report.to_github_annotations():
                typer.echo(line)

        # ── Exit code (uses all findings, independent of --severity display filter) ──
        if fail_on:
            threshold = _SEVERITY_ORDER[fail_on]
            if any(_SEVERITY_ORDER.get(f.severity, 2) <= threshold for f in report.findings):
                raise typer.Exit(1)
    finally:
        conn.close()


def _print_scan_report(report: object, findings: list) -> None:
    """Render a human-readable scan report."""
    from nbadb.orchestrate.scanner import ScanReport

    assert isinstance(report, ScanReport)

    summary = report.summary()
    typer.echo(
        f"\nScan complete: {summary['checks_run']} checks, "
        f"{summary['tables_scanned']} tables scanned "
        f"({report.duration_seconds:.1f}s)"
    )
    typer.echo(
        f"Findings: {summary['error']} errors, "
        f"{summary['warning']} warnings, {summary['info']} info\n"
    )

    if not findings:
        typer.echo("No issues found.")
        return

    # Group by category
    by_category: dict[str, list] = {}
    for f in findings:
        by_category.setdefault(f.category, []).append(f)

    severity_icons = {"error": "ERR ", "warning": "WARN", "info": "INFO"}
    category_order = ["missing_table", "cross_table", "temporal", "data_quality"]

    for cat in category_order:
        cat_findings = by_category.get(cat, [])
        if not cat_findings:
            continue
        typer.echo(f"--- {cat.upper().replace('_', ' ')} ({len(cat_findings)}) ---")
        for f in cat_findings:
            icon = severity_icons.get(f.severity, "    ")
            typer.echo(f"  [{icon}] {f.message}")
        typer.echo("")
