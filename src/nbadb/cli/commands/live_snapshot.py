from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings, _format_pipeline_exception, _setup_logging
from nbadb.cli.options import DataDirOption, VerboseOption  # noqa: TC001
from nbadb.orchestrate import LiveSnapshotWarehouse

_GAME_ID_OPTION = typer.Option(
    None,
    "--game-id",
    help="Explicit live game id to snapshot. Repeat to force specific live games.",
)
_SNAPSHOT_AT_OPTION = typer.Option(
    None,
    "--snapshot-at",
    help="Optional ISO-8601 snapshot timestamp override.",
)


def _parse_snapshot_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("Expected an ISO-8601 timestamp") from exc


@app.command("live-snapshot")
def live_snapshot(
    data_dir: DataDirOption = None,
    game_id: list[str] | None = _GAME_ID_OPTION,
    snapshot_at: str | None = _SNAPSHOT_AT_OPTION,
    verbose: VerboseOption = False,
) -> None:
    """Append a live snapshot for active games or explicit game ids."""
    _setup_logging(verbose)
    settings = _build_settings(data_dir)
    warehouse = LiveSnapshotWarehouse(settings=settings)

    try:
        result = warehouse.run(
            game_ids=list(game_id) if game_id else None,
            snapshot_at=_parse_snapshot_at(snapshot_at),
        )
    except Exception as exc:
        typer.echo(f"live-snapshot failed: {_format_pipeline_exception(exc)}", err=True)
        raise typer.Exit(1) from exc

    if result.game_ids:
        typer.echo(
            "live-snapshot complete: "
            f"{len(result.game_ids)} games | "
            f"{result.star_tables_loaded} star tables | "
            f"{result.star_rows_loaded:,} rows"
        )
    else:
        typer.echo("live-snapshot complete: no active live games")

    if data_dir is not None:
        typer.echo(f"  data-dir: {Path(data_dir)}")
