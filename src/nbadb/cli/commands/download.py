from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.options import DataDirOption  # noqa: TC001


@app.command()
def download(
    data_dir: DataDirOption = None,
) -> None:
    """Pull latest dataset from Kaggle."""
    from nbadb.kaggle.client import KaggleClient

    try:
        path = KaggleClient().download(data_dir)
    except Exception as exc:
        typer.echo(f"Download failed: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Downloaded to {path}")
