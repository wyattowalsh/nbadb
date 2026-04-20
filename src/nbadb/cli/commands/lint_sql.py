from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table

from nbadb.cli.app import app

if TYPE_CHECKING:
    from sqlfluff.core.errors import SQLBaseError

    from nbadb.transform.base import SqlTransformer

console = Console()


def _normalize_fixed_sql(maybe_fixed: object, fallback_sql: str) -> str:
    if isinstance(maybe_fixed, tuple):
        if maybe_fixed:
            first = maybe_fixed[0]
            if isinstance(first, str):
                return first
        return fallback_sql
    if isinstance(maybe_fixed, str):
        return maybe_fixed
    return fallback_sql


def _extract_fix_outcome(
    linter: object,
    linted: object,
    sql: str,
) -> tuple[str, list[SQLBaseError]]:
    violations = getattr(linted, "violations", [])

    fix_method = getattr(linter, "fix_string", None)
    if callable(fix_method):
        fix_result = fix_method(sql)
        if hasattr(fix_result, "fix_string") or hasattr(fix_result, "violations"):
            return (
                _normalize_fixed_sql(getattr(fix_result, "fix_string", sql), sql),
                getattr(fix_result, "violations", violations),
            )
        return _normalize_fixed_sql(fix_result, sql), violations

    fix_result = getattr(linted, "fix_string", None)
    if callable(fix_result):
        fix_result = fix_result()
    if fix_result is not None:
        return _normalize_fixed_sql(fix_result, sql), violations

    return sql, violations


@app.command("lint-sql")
def lint_sql(
    fix: Annotated[
        bool,
        typer.Option("--fix", help="Auto-fix violations in-place (rewrites _SQL ClassVars)"),
    ] = False,
    table: Annotated[
        str | None,
        typer.Option("--table", "-t", help="Filter to a specific output_table name"),
    ] = None,
    fail_on: Annotated[
        str | None,
        typer.Option(
            "--fail-on",
            "-F",
            help="Exit 1 if violations at or above this severity: error, warning",
        ),
    ] = None,
) -> None:
    """Lint SQL in SqlTransformer _SQL ClassVars using SQLFluff (DuckDB dialect)."""
    try:
        from sqlfluff.core import Linter
    except ImportError:
        typer.echo(
            "sqlfluff is not installed. Install with: uv add --dev sqlfluff",
            err=True,
        )
        raise typer.Exit(1) from None

    from nbadb.orchestrate.transformers import discover_all_transformers
    from nbadb.transform.base import SqlTransformer

    transformers = discover_all_transformers()
    sql_transformers: list[SqlTransformer] = [
        t for t in transformers if isinstance(t, SqlTransformer) and t._SQL.strip()
    ]

    if table:
        sql_transformers = [t for t in sql_transformers if t.output_table == table]

    if not sql_transformers:
        typer.echo("No SqlTransformers found to lint.")
        raise typer.Exit(0)

    linter = Linter(dialect="duckdb")
    total_violations = 0
    total_fixed = 0
    results: list[tuple[str, str, list[SQLBaseError]]] = []

    for t in sorted(sql_transformers, key=lambda x: x.output_table):
        sql = textwrap.dedent(t._SQL).strip() + "\n"

        linted = linter.lint_string(sql, fix=fix)
        violations = getattr(linted, "violations", [])

        if fix:
            fixed_sql, violations = _extract_fix_outcome(linter, linted, sql)
            if fixed_sql != sql:
                total_fixed += 1
                _write_fix(t, fixed_sql)

        if violations:
            total_violations += len(violations)
            results.append((t.output_table, type(t).__name__, violations))

    # Display results
    if results:
        tbl = Table(title="SQLFluff Violations", show_lines=True)
        tbl.add_column("Table", style="cyan", no_wrap=True)
        tbl.add_column("Rule", style="yellow", no_wrap=True)
        tbl.add_column("Line", justify="right")
        tbl.add_column("Description")

        for output_table, _class_name, violations in results:
            for v in violations:
                tbl.add_row(
                    output_table,
                    v.rule_code(),
                    str(v.line_no),
                    v.desc(),
                )

        console.print(tbl)

    typer.echo(
        f"\nLinted {len(sql_transformers)} transforms: "
        f"{total_violations} violation(s) found" + (f", {total_fixed} auto-fixed" if fix else "")
    )

    if fail_on:
        severity_map = {"error": {"error"}, "warning": {"error", "warning"}}
        target = severity_map.get(fail_on, {"error"})
        for _, _, violations in results:
            for v in violations:
                if getattr(v, "severity", "warning") in target:
                    raise typer.Exit(1)

    if total_violations > 0 and not fix:
        raise typer.Exit(1)


def _write_fix(transformer: SqlTransformer, fixed_sql: str) -> None:
    """Write the fixed SQL back into the transformer's source file."""
    import inspect

    src_file = inspect.getfile(transformer.__class__)
    if not src_file:
        return

    with open(src_file, encoding="utf-8") as f:
        source = f.read()

    # Find the _SQL ClassVar and replace its content
    original_sql = transformer._SQL
    if original_sql in source:
        source = source.replace(original_sql, fixed_sql.rstrip("\n"), 1)
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(source)
        typer.echo(f"  Fixed: {transformer.__class__.__name__} ({src_file})")
