from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.docs_gen.autogen import DEFAULT_DOCS_ROOT, check_docs_artifacts, generate_docs_artifacts

DocsRootOption = Annotated[
    Path,
    typer.Option("--docs-root", help="Docs content root directory"),
]


@app.command("docs-autogen")
def docs_autogen(
    docs_root: DocsRootOption = DEFAULT_DOCS_ROOT,
    check: Annotated[
        bool,
        typer.Option("--check", help="Check generated docs artifacts without writing files"),
    ] = False,
) -> None:
    """Generate docs artifacts from schema metadata."""
    if check:
        stale_paths = check_docs_artifacts(docs_root)
        if stale_paths:
            for path in stale_paths:
                typer.echo(f"stale: {path}")
            raise typer.Exit(1)
        typer.echo("Docs autogen check passed.")
        return

    updated_paths, unchanged_paths = generate_docs_artifacts(docs_root)

    for path in updated_paths:
        typer.echo(f"updated: {path}")
    for path in unchanged_paths:
        typer.echo(f"unchanged: {path}")
    typer.echo(
        f"Docs autogen complete ({len(updated_paths)} updated, {len(unchanged_paths)} unchanged)."
    )
