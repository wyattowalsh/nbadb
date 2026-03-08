from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from nbadb.cli.app import app
from nbadb.docs_gen.autogen import DEFAULT_DOCS_ROOT, generate_docs_artifacts

DocsRootOption = Annotated[
    Path,
    typer.Option("--docs-root", help="Docs content root directory"),
]


@app.command("docs-autogen")
def docs_autogen(
    docs_root: DocsRootOption = DEFAULT_DOCS_ROOT,
) -> None:
    """Generate docs artifacts from schema metadata."""
    updated_paths, unchanged_paths = generate_docs_artifacts(docs_root)

    for path in updated_paths:
        typer.echo(f"updated: {path}")
    for path in unchanged_paths:
        typer.echo(f"unchanged: {path}")
    typer.echo(
        f"Docs autogen complete ({len(updated_paths)} updated, {len(unchanged_paths)} unchanged)."
    )
