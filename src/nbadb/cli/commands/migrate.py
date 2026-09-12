from __future__ import annotations

import typer

from nbadb.cli.app import app
from nbadb.cli.commands._helpers import _build_settings
from nbadb.cli.options import DataDirOption  # noqa: TC001


@app.command()
def migrate(
    data_dir: DataDirOption = None,
) -> None:
    """Create or migrate pipeline tables in the DuckDB database."""
    from nbadb.core.db import DBManager, TransformOutputAuthorityPersistenceState

    settings = _build_settings(data_dir)

    if settings.sqlite_path is None:
        typer.echo("Error: sqlite_path not configured.", err=True)
        raise typer.Exit(1)

    if settings.duckdb_path is None:
        typer.echo("Error: duckdb_path not configured.", err=True)
        raise typer.Exit(1)

    db = DBManager(
        sqlite_path=settings.sqlite_path,
        duckdb_path=settings.duckdb_path,
    )
    try:
        db.init()
        authority_state = db.install_transform_output_authority_persistence()
        if authority_state.state is not TransformOutputAuthorityPersistenceState.ALREADY_CURRENT:
            raise RuntimeError(
                "transform-output authority persistence requires explicit repair: "
                f"{authority_state.reason_code}"
            )
        typer.echo("Migration complete.")
    except Exception as exc:
        typer.echo(f"Migration failed: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from exc
    finally:
        db.close()
