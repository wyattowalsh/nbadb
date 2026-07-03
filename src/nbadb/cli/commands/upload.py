from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings
from nbadb.cli.options import DataDirOption  # noqa: TC001


@app.command()
def upload(
    data_dir: DataDirOption = None,
    message: str = typer.Option(
        "Automated update",
        "--message",
        "-m",
        help="Version notes for Kaggle upload",
    ),
    verify_remote: bool = typer.Option(
        False,
        "--verify-remote",
        help=(
            "Download the latest Kaggle dataset after upload and verify bundle fingerprint parity."
        ),
    ),
) -> None:
    """Push data to Kaggle."""
    from nbadb.kaggle.client import KaggleClient

    settings = _build_settings(data_dir)
    try:
        client = KaggleClient()
        client.ensure_metadata(settings.data_dir)
        manifest_path = client.upload(
            settings.data_dir,
            version_notes=message,
            verify_remote=verify_remote,
        )
    except Exception as exc:
        typer.echo(f"Upload failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc
    if manifest_path is not None:
        typer.echo(f"Upload manifest: {manifest_path}")
    typer.echo("Upload complete")
