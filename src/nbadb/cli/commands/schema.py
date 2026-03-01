from __future__ import annotations

import importlib
import inspect
import pkgutil

import typer

from nbadb.cli.app import app
from nbadb.transform.base import BaseTransformer


@app.command()
def schema(
    table: str = typer.Argument(
        None, help="Table name (omit to list all)"
    ),
) -> None:
    """Display star schema info and table lineage."""
    transformers = _discover_all_transformers()

    if table:
        _show_table_detail(table, transformers)
    else:
        _show_all_tables(transformers)


def _discover_all_transformers() -> list[BaseTransformer]:
    """Walk nbadb.transform subpackages and instantiate transformers."""
    import nbadb.transform as root_pkg

    instances: list[BaseTransformer] = []
    for _, modname, _ispkg in pkgutil.walk_packages(
        root_pkg.__path__,
        prefix=root_pkg.__name__ + ".",
    ):
        try:
            mod = importlib.import_module(modname)
        except (ImportError, ModuleNotFoundError):
            continue
        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, BaseTransformer)
                and obj is not BaseTransformer
                and hasattr(obj, "output_table")
            ):
                try:
                    instances.append(obj())
                except (TypeError, ValueError, RuntimeError):
                    continue
    return instances


def _show_table_detail(
    table: str,
    transformers: list[BaseTransformer],
) -> None:
    """Show detail for a single table."""
    match = [t for t in transformers if t.output_table == table]
    if not match:
        typer.echo(f"Table '{table}' not found in transformers.")
        typer.echo("Run 'nbadb schema' to list all tables.")
        raise typer.Exit(1)
    t = match[0]
    typer.echo(f"Table:      {t.output_table}")
    typer.echo(f"Class:      {type(t).__name__}")
    typer.echo(
        f"Depends on: {', '.join(t.depends_on) or '(none)'}"
    )


def _show_all_tables(
    transformers: list[BaseTransformer],
) -> None:
    """List all tables grouped by prefix type."""
    groups: dict[str, list[str]] = {
        "Dimensions (dim_)": [],
        "Facts (fact_)": [],
        "Bridges (bridge_)": [],
        "Aggregates (agg_)": [],
        "Analytics (analytics_)": [],
        "Other": [],
    }
    for t in transformers:
        name = t.output_table
        if name.startswith("dim_"):
            groups["Dimensions (dim_)"].append(name)
        elif name.startswith("fact_"):
            groups["Facts (fact_)"].append(name)
        elif name.startswith("bridge_"):
            groups["Bridges (bridge_)"].append(name)
        elif name.startswith("agg_"):
            groups["Aggregates (agg_)"].append(name)
        elif name.startswith("analytics_"):
            groups["Analytics (analytics_)"].append(name)
        else:
            groups["Other"].append(name)

    total = 0
    for label, tables in groups.items():
        if not tables:
            continue
        tables.sort()
        typer.echo(f"\n{label} ({len(tables)})")
        for name in tables:
            typer.echo(f"  {name}")
        total += len(tables)
    typer.echo(f"\nTotal: {total} tables")
