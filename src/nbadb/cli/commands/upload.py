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
            "Verify the exact Kaggle version, complete remote file inventory, and full-bundle "
            "SHA-256 identity."
        ),
    ),
    remote_timeout: float = typer.Option(
        3600.0,
        "--remote-timeout",
        min=0.0,
        help="Seconds allowed for each Kaggle reconciliation or post-upload readback phase.",
    ),
    remote_poll_interval: float = typer.Option(
        15.0,
        "--remote-poll-interval",
        min=0.1,
        help="Seconds between Kaggle remote verification attempts.",
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
            remote_timeout_seconds=remote_timeout,
            remote_poll_interval_seconds=remote_poll_interval,
        )
    except Exception as exc:
        typer.echo(f"Upload failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc
    if manifest_path is not None:
        typer.echo(f"Upload manifest: {manifest_path}")
    typer.echo("Upload complete")
