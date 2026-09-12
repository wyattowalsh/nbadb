from __future__ import annotations

from pathlib import Path

import typer

from nbadb.cli.app import app
from nbadb.cli.options import DataDirOption  # noqa: TC001


class _DownloadOptionError(ValueError):
    """A caller-facing validation error whose message contains no remote data."""


@app.command()
def download(
    data_dir: DataDirOption = None,
    verified_public_baseline: bool = typer.Option(
        False,
        "--verified-public-baseline",
        help=(
            "Install one exact caller-selected Kaggle version after complete SHA-256 readback "
            "and full-publication assurance validation."
        ),
    ),
    dataset_version: int | None = typer.Option(
        None,
        "--dataset-version",
        min=1,
        help="Exact positive Kaggle dataset version required for verified baseline mode.",
    ),
    publication_ledger: str = typer.Option(
        "local",
        "--publication-ledger",
        help="Baseline reconciliation ledger: local or github-deployment.",
    ),
    require_durable_reconciliation: bool = typer.Option(
        False,
        "--require-durable-reconciliation",
        help="Fail closed unless the GitHub Deployment ledger is checked and reconciled.",
    ),
    receipt_path: str = typer.Option(
        "logs/kaggle/nbadb-public-baseline-receipt.json",
        "--receipt-path",
        help="Canonical verified-public-baseline receipt path.",
    ),
    remote_timeout: float = typer.Option(
        3600.0,
        "--remote-timeout",
        min=0.1,
        help="Seconds allowed for exact inventory download, validation, and reconciliation.",
    ),
) -> None:
    """Pull a Kaggle dataset for interactive use or an assured recurring baseline."""
    from nbadb.kaggle.client import KaggleClient

    try:
        ledger_mode = publication_ledger.strip().lower()
        if ledger_mode not in {"local", "github-deployment"}:
            raise _DownloadOptionError(
                "Unsupported Kaggle baseline ledger; expected local or github-deployment"
            )
        if require_durable_reconciliation and ledger_mode != "github-deployment":
            raise _DownloadOptionError(
                "--require-durable-reconciliation requires --publication-ledger github-deployment"
            )
        if not verified_public_baseline and (
            ledger_mode != "local" or require_durable_reconciliation or dataset_version is not None
        ):
            raise _DownloadOptionError(
                "Kaggle baseline ledger and dataset-version options require "
                "--verified-public-baseline"
            )
        if verified_public_baseline and dataset_version is None:
            raise _DownloadOptionError("--verified-public-baseline requires --dataset-version")

        client = KaggleClient()
        if not verified_public_baseline:
            path = client.download(data_dir)
            typer.echo(f"Downloaded to {path}")
            return

        durable_ledger = None
        if ledger_mode == "github-deployment":
            from nbadb.kaggle.publication_ledger import (
                GitHubDeploymentPublicationLedger,
            )

            durable_ledger = GitHubDeploymentPublicationLedger.from_actions_env()
        exact_dataset_version = dataset_version
        if exact_dataset_version is None:
            raise AssertionError("verified public baseline lost its exact dataset version")
        path, emitted_receipt = client.download_verified_public_baseline(
            data_dir,
            dataset_version=exact_dataset_version,
            receipt_path=Path(receipt_path),
            remote_timeout_seconds=remote_timeout,
            publication_ledger=durable_ledger,
            require_durable_reconciliation=require_durable_reconciliation,
        )
    except _DownloadOptionError as exc:
        typer.echo(f"Download failed: ValueError: {exc}", err=True)
        raise typer.Exit(1) from exc
    except Exception as exc:
        typer.echo(f"Download failed: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Verified public baseline installed at {path}")
    typer.echo(f"Baseline receipt: {emitted_receipt}")
