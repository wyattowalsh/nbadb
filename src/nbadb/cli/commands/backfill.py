from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated

if TYPE_CHECKING:
    from pathlib import Path

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings, _open_db_readonly, _run_pipeline
from nbadb.cli.options import DataDirOption, VerboseOption  # noqa: TC001
from nbadb.orchestrate import Orchestrator

backfill_app = typer.Typer(
    name="backfill",
    help="Targeted backfill: gap detection, selective extraction, completeness reporting.",
    no_args_is_help=True,
)
app.add_typer(backfill_app)


_VALID_STATUSES = {"done", "failed", "abandoned", "running"}

# ── shared option types ──────────────────────────────────────────

SeasonsOption = Annotated[
    str | None,
    typer.Option(
        "--seasons",
        "-s",
        help="Comma-separated seasons or range: '2015-16,2016-17' or '2015:2020'",
    ),
]
EndpointOption = Annotated[
    str | None,
    typer.Option(
        "--endpoint",
        "-e",
        help="Comma-separated endpoint names (e.g. 'box_score_traditional,play_by_play')",
    ),
]
PatternOption = Annotated[
    str | None,
    typer.Option(
        "--pattern",
        "-p",
        help="Comma-separated param patterns (e.g. 'game,season')",
    ),
]
OutputFormatOption = Annotated[
    str,
    typer.Option("--output-format", "-f", help="Output format: text or json"),
]


# ── parsing helpers ──────────────────────────────────────────────


def _parse_seasons(raw: str | None) -> list[str] | None:
    """Parse season strings.

    Accepts:
    - ``"2015-16,2016-17"`` — comma-separated season strings
    - ``"2015:2020"`` — inclusive range (start year : end year)
    - ``"2024"`` — single year (converted to ``"2024-25"``)
    """
    if raw is None:
        return None

    from nbadb.orchestrate.seasons import season_range, season_string

    parts = [s.strip() for s in raw.split(",")]
    result: list[str] = []

    for part in parts:
        if ":" in part:
            start_s, end_s = part.split(":", 1)
            try:
                start_val, end_val = int(start_s), int(end_s)
            except ValueError:
                raise typer.BadParameter(f"Invalid season range: {part}") from None
            if start_val > end_val:
                raise typer.BadParameter(
                    f"Reversed season range: {part} (start {start_val} > end {end_val})"
                )
            result.extend(season_range(start_val, end_val))
        elif "-" in part and len(part) == 7 and part[4] == "-":
            try:
                int(part[:4])
                int(part[5:7])
            except ValueError:
                raise typer.BadParameter(f"Invalid season format: {part}") from None
            result.append(part)
        else:
            try:
                result.append(season_string(int(part)))
            except ValueError:
                raise typer.BadParameter(f"Invalid season: {part}") from None

    return result


def _parse_csv(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


# ── subcommands ──────────────────────────────────────────────────


@backfill_app.command()
def run(
    data_dir: DataDirOption = None,
    seasons: SeasonsOption = None,
    endpoint: EndpointOption = None,
    pattern: PatternOption = None,
    force: bool = typer.Option(False, "--force", help="Reset done entries to re-extract"),
    extract_only: bool = typer.Option(False, "--extract-only", help="Skip transform+load"),
    transform_only: bool = typer.Option(
        False, "--transform-only", help="Re-run transforms only (no extraction)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show plan without executing"),
    verbose: VerboseOption = False,
    quality_check: bool = typer.Option(
        False, "--quality-check", help="Run quality checks after pipeline"
    ),
) -> None:
    """Execute targeted backfill extraction."""
    parsed_seasons = _parse_seasons(seasons)
    parsed_endpoints = _parse_csv(endpoint)
    parsed_patterns = _parse_csv(pattern)

    if extract_only and transform_only:
        typer.echo("Cannot use --extract-only and --transform-only together", err=True)
        raise typer.Exit(1)

    if dry_run:
        _dry_run(
            data_dir=data_dir,
            seasons=parsed_seasons,
            endpoints=parsed_endpoints,
            patterns=parsed_patterns,
            force=force,
        )
        return

    settings = _build_settings(data_dir)
    _run_pipeline(
        "backfill",
        lambda orch: orch.run_backfill(
            seasons=parsed_seasons,
            endpoints=parsed_endpoints,
            patterns=parsed_patterns,
            force=force,
            extract_only=extract_only,
            transform_only=transform_only,
        ),
        settings,
        verbose,
        quality_check,
        orchestrator_cls=Orchestrator,
    )


def _dry_run(
    *,
    data_dir: Path | None,
    seasons: list[str] | None,
    endpoints: list[str] | None,
    patterns: list[str] | None,
    force: bool,
) -> None:
    """Print what backfill would do without executing."""
    from nbadb.orchestrate.backfill import BackfillPlanner
    from nbadb.orchestrate.journal import PipelineJournal

    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path
    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.")
        raise typer.Exit(1)

    conn = _open_db_readonly(db_path)
    try:
        journal = PipelineJournal(conn)
        planner = BackfillPlanner(conn, journal)
        plan = planner.build_plan(
            seasons=seasons,
            endpoints=endpoints,
            patterns=patterns,
            force=force,
        )
        typer.echo(plan.dry_run_summary)
    finally:
        conn.close()


@backfill_app.command()
def gaps(
    data_dir: DataDirOption = None,
    seasons: SeasonsOption = None,
    endpoint: EndpointOption = None,
    pattern: PatternOption = None,
    output_format: OutputFormatOption = "text",
) -> None:
    """Detect and report extraction gaps."""
    parsed_seasons = _parse_seasons(seasons)
    parsed_endpoints = _parse_csv(endpoint)
    parsed_patterns = _parse_csv(pattern)

    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path
    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.")
        raise typer.Exit(1)

    from nbadb.orchestrate.backfill import BackfillPlanner
    from nbadb.orchestrate.journal import PipelineJournal

    conn = _open_db_readonly(db_path)
    try:
        journal = PipelineJournal(conn)
        planner = BackfillPlanner(conn, journal)
        report = planner.detect_gaps(
            seasons=parsed_seasons,
            endpoints=parsed_endpoints,
            patterns=parsed_patterns,
        )

        if output_format == "json":
            data = {
                "gaps": [
                    {
                        "endpoint": g.endpoint,
                        "season": g.season,
                        "pattern": g.pattern,
                        "expected": g.expected,
                        "actual": g.actual,
                        "missing": g.missing,
                    }
                    for g in report.gaps
                ],
                "summary": report.summary,
            }
            typer.echo(json.dumps(data, indent=2, default=str))
        else:
            _print_gap_report(report)
    finally:
        conn.close()


def _print_gap_report(report: object) -> None:
    """Render a text gap report."""
    from nbadb.orchestrate.backfill import CompletenessReport

    assert isinstance(report, CompletenessReport)

    if not report.gaps:
        typer.echo("No gaps detected.")
        return

    typer.echo(
        f"\n{'Endpoint':<35} {'Season':<10} {'Pattern':<15} "
        f"{'Expected':>10} {'Actual':>8} {'Missing':>8}"
    )
    typer.echo("-" * 90)

    for gap in report.gaps:
        expected_str = str(gap.expected) if gap.expected is not None else "?"
        missing_str = str(gap.missing) if gap.missing is not None else "?"
        season_str = gap.season or "all"
        typer.echo(
            f"{gap.endpoint:<35} {season_str:<10} {gap.pattern:<15} "
            f"{expected_str:>10} {gap.actual:>8} {missing_str:>8}"
        )

    typer.echo(f"\nSummary by pattern: {report.summary}")


@backfill_app.command()
def completeness(
    data_dir: DataDirOption = None,
    seasons: SeasonsOption = None,
    endpoint: EndpointOption = None,
    output_format: OutputFormatOption = "text",
) -> None:
    """Show data completeness per season, per endpoint."""
    parsed_seasons = _parse_seasons(seasons)
    parsed_endpoints = _parse_csv(endpoint)

    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path
    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.")
        raise typer.Exit(1)

    from nbadb.orchestrate.backfill import BackfillPlanner
    from nbadb.orchestrate.journal import PipelineJournal

    conn = _open_db_readonly(db_path)
    try:
        journal = PipelineJournal(conn)
        planner = BackfillPlanner(conn, journal)
        report = planner.detect_gaps(
            seasons=parsed_seasons,
            endpoints=parsed_endpoints,
        )

        if output_format == "json":
            data = {
                "summary": report.summary,
                "by_season": report.by_season,
                "by_endpoint": report.by_endpoint,
                "total_gaps": len(report.gaps),
            }
            typer.echo(json.dumps(data, indent=2, default=str))
        else:
            _print_completeness(report)
    finally:
        conn.close()


def _print_completeness(report: object) -> None:
    """Render a text completeness report."""
    from nbadb.orchestrate.backfill import CompletenessReport

    assert isinstance(report, CompletenessReport)

    if not report.gaps:
        typer.echo("All endpoints complete.")
        return

    typer.echo(f"\nTotal gaps: {len(report.gaps)}")
    typer.echo(f"By pattern: {report.summary}")

    if report.by_endpoint:
        typer.echo("\nBy endpoint:")
        for ep, season_gaps in sorted(report.by_endpoint.items()):
            total_missing = sum(season_gaps.values())
            typer.echo(f"  {ep}: {total_missing} missing across {len(season_gaps)} seasons")

    if report.by_season:
        typer.echo("\nBy season:")
        for season, ep_gaps in sorted(report.by_season.items()):
            total_missing = sum(ep_gaps.values())
            typer.echo(f"  {season}: {total_missing} missing across {len(ep_gaps)} endpoints")


@backfill_app.command("journal")
def journal_cmd(
    data_dir: DataDirOption = None,
    endpoint: EndpointOption = None,
    seasons: SeasonsOption = None,
    status_filter: str | None = typer.Option(
        None, "--status", help="Filter by status: done/failed/abandoned"
    ),
    action: str = typer.Option("show", "--action", "-a", help="Action: show/count/reset/clear"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation for reset/clear"),
    output_format: OutputFormatOption = "text",
) -> None:
    """Manage extraction journal entries selectively."""
    import duckdb

    parsed_endpoints = _parse_csv(endpoint)
    parsed_seasons = _parse_seasons(seasons)

    settings = _build_settings(data_dir)
    db_path = settings.duckdb_path
    if db_path is None or not db_path.exists():
        typer.echo("Database not found. Run 'nbadb init' first.")
        raise typer.Exit(1)

    if status_filter is not None and status_filter not in _VALID_STATUSES:
        typer.echo(
            f"Invalid status: {status_filter}. "
            f"Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
            err=True,
        )
        raise typer.Exit(1)

    if action in ("show", "count"):
        conn = _open_db_readonly(db_path)
    else:
        conn = duckdb.connect(str(db_path))

    try:
        from nbadb.orchestrate.journal import PipelineJournal

        journal = PipelineJournal(conn)

        if action == "count":
            _journal_count(journal, output_format)
        elif action == "show":
            _journal_show(journal, parsed_endpoints, parsed_seasons, status_filter, output_format)
        elif action == "reset":
            _journal_reset(journal, parsed_endpoints, parsed_seasons, status_filter, yes)
        elif action == "clear":
            _journal_clear(journal, parsed_endpoints, parsed_seasons, status_filter, yes)
        else:
            typer.echo(f"Unknown action: {action}. Use show/count/reset/clear.", err=True)
            raise typer.Exit(1)
    finally:
        conn.close()


def _journal_count(journal: object, output_format: str) -> None:
    from nbadb.orchestrate.journal import PipelineJournal

    assert isinstance(journal, PipelineJournal)
    counts = journal.count_by_endpoint_and_status()

    if output_format == "json":
        data = [{"endpoint": ep, "status": st, "count": cnt} for ep, st, cnt in counts]
        typer.echo(json.dumps(data, indent=2))
    else:
        if not counts:
            typer.echo("Journal is empty.")
            return
        typer.echo(f"\n{'Endpoint':<35} {'Status':<12} {'Count':>8}")
        typer.echo("-" * 58)
        for ep, st, cnt in counts:
            typer.echo(f"{ep:<35} {st:<12} {cnt:>8}")


def _journal_show(
    journal: object,
    endpoints: list[str] | None,
    seasons: list[str] | None,
    status_filter: str | None,
    output_format: str,
) -> None:
    """Show journal entries filtered by endpoint/season/status."""
    from nbadb.orchestrate.journal import PipelineJournal

    assert isinstance(journal, PipelineJournal)

    rows = journal.fetch_entries(
        endpoints=endpoints,
        seasons=seasons,
        status_filter=status_filter,
        limit=100,
    )

    if output_format == "json":
        data = [
            {
                "endpoint": r[0],
                "params": r[1],
                "status": r[2],
                "retry_count": r[3],
                "started_at": r[4],
            }
            for r in rows
        ]
        typer.echo(json.dumps(data, indent=2))
    else:
        if not rows:
            typer.echo("No matching journal entries.")
            return
        typer.echo(f"\n{'Endpoint':<30} {'Status':<10} {'Retries':>7}  Params")
        typer.echo("-" * 80)
        for r in rows:
            params_short = r[1][:30] + "..." if len(r[1]) > 33 else r[1]
            typer.echo(f"{r[0]:<30} {r[2]:<10} {r[3]:>7}  {params_short}")
        if len(rows) == 100:
            typer.echo("\n(showing first 100 entries)")


def _journal_reset(
    journal: object,
    endpoints: list[str] | None,
    seasons: list[str] | None,
    status_filter: str | None,
    yes: bool,
) -> None:
    from nbadb.orchestrate.journal import PipelineJournal

    assert isinstance(journal, PipelineJournal)

    desc = _describe_filters(endpoints, seasons, status_filter)
    if not yes:
        typer.confirm(f"Reset journal entries matching: {desc}?", abort=True)

    if not endpoints and not seasons and not status_filter:
        typer.echo("Provide at least one of --endpoint, --seasons, or --status", err=True)
        raise typer.Exit(1)

    total = 0
    for endpoint in endpoints or [None]:
        for season in seasons or [None]:
            total += journal.reset_entries(
                endpoint=endpoint,
                status_filter=status_filter,
                season_like=season,
            )

    typer.echo(f"Reset {total} journal entries.")


def _journal_clear(
    journal: object,
    endpoints: list[str] | None,
    seasons: list[str] | None,
    status_filter: str | None,
    yes: bool,
) -> None:
    from nbadb.orchestrate.journal import PipelineJournal

    assert isinstance(journal, PipelineJournal)

    desc = _describe_filters(endpoints, seasons, status_filter)
    if not yes:
        typer.confirm(
            f"DELETE journal entries matching: {desc}? This cannot be undone.",
            abort=True,
        )

    if not endpoints and not seasons and not status_filter:
        typer.echo("Provide at least one of --endpoint, --seasons, or --status", err=True)
        raise typer.Exit(1)

    total = 0
    for endpoint in endpoints or [None]:
        for season in seasons or [None]:
            total += journal.clear_entries(
                endpoint=endpoint,
                status_filter=status_filter,
                season_like=season,
            )

    typer.echo(f"Cleared {total} journal entries.")


def _describe_filters(
    endpoints: list[str] | None,
    seasons: list[str] | None,
    status_filter: str | None,
) -> str:
    parts: list[str] = []
    if endpoints:
        parts.append(f"endpoint={','.join(endpoints)}")
    if seasons:
        parts.append(f"seasons={','.join(seasons)}")
    if status_filter:
        parts.append(f"status={status_filter}")
    return " AND ".join(parts) if parts else "(all)"
