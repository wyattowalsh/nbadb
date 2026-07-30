from __future__ import annotations

import json

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings
from nbadb.cli.options import DataDirOption  # noqa: TC001

_REMOTE_VERIFIED_STATUSES = frozenset({"uploaded_remote_verified", "reconciled_existing_remote"})
_SUBMITTED_STATUSES = frozenset({"uploaded_unverified"})


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
    full_publication: bool = typer.Option(
        False,
        "--full-publication",
        help=(
            "Require matching assured and terminal-assurance provenance; implies exact remote "
            "verification."
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
    publication_ledger: str = typer.Option(
        "local",
        "--publication-ledger",
        help="Publication intent ledger: local or github-deployment.",
    ),
    require_durable_intent: bool = typer.Option(
        False,
        "--require-durable-intent",
        help="Fail closed unless a crash-durable external publication intent is active.",
    ),
) -> None:
    """Push data to Kaggle."""
    from nbadb.kaggle.client import KaggleClient

    settings = _build_settings(data_dir)
    remote_verification = verify_remote or full_publication
    try:
        ledger_mode = publication_ledger.strip().lower()
        if ledger_mode not in {"local", "github-deployment"}:
            msg = (
                "Unsupported Kaggle publication ledger: "
                f"{publication_ledger!r}; expected local or github-deployment"
            )
            raise ValueError(msg)
        if require_durable_intent and ledger_mode != "github-deployment":
            raise ValueError(
                "--require-durable-intent requires --publication-ledger github-deployment"
            )
        if ledger_mode == "github-deployment" and not remote_verification:
            raise ValueError(
                "--publication-ledger github-deployment requires --verify-remote "
                "or --full-publication"
            )
        durable_ledger = None
        if ledger_mode == "github-deployment":
            from nbadb.kaggle.publication_ledger import (
                GitHubDeploymentPublicationLedger,
            )

            durable_ledger = GitHubDeploymentPublicationLedger.from_actions_env()

        client = KaggleClient()
        client.ensure_metadata(
            settings.data_dir,
            include_assurance_resources=full_publication,
        )
        manifest_path = client.upload(
            settings.data_dir,
            version_notes=message,
            verify_remote=verify_remote,
            require_assured=full_publication,
            full_publication=full_publication,
            remote_timeout_seconds=remote_timeout,
            remote_poll_interval_seconds=remote_poll_interval,
            publication_ledger=durable_ledger,
            require_durable_intent=require_durable_intent,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        status = manifest.get("status")
        if not isinstance(status, str):
            msg = "Kaggle upload manifest is missing a valid status"
            raise RuntimeError(msg)
        accepted_statuses = (
            _REMOTE_VERIFIED_STATUSES if remote_verification else _SUBMITTED_STATUSES
        )
        if status not in accepted_statuses:
            mode = "remote-verified" if remote_verification else "submitted"
            msg = f"Kaggle upload returned unexpected {mode} status: {status}"
            raise RuntimeError(msg)
    except Exception as exc:
        typer.echo(f"Upload failed: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Upload manifest: {manifest_path}")
    if remote_verification:
        typer.echo("Upload complete")
    else:
        typer.echo("Upload submitted/unverified")
