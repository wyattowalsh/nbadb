from __future__ import annotations

import typer

app = typer.Typer(
    name="nbadb",
    help="Comprehensive NBA database: broad nba_api coverage → 141-table star schema",
    no_args_is_help=True,
)

# Register command modules (each imports `app` and decorates with @app.command)
from nbadb.cli.commands import (  # noqa: E402, F401
    ask,
    backfill,
    chat,
    daily,
    docs_autogen,
    download,
    export,
    extract_completeness,
    full,
    init,
    migrate,
    monthly,
    run_quality,
    scan,
    schema,
    status,
    upload,
)
