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
    audit_models,
    backfill,
    chat,
    daily,
    docs_autogen,
    download,
    endpoint_adequacy_scorecard,
    endpoint_support_matrix,
    export,
    extract_completeness,
    full,
    init,
    lint_sql,
    live_snapshot,
    metadata,
    migrate,
    monthly,
    scan,
    schema,
    schema_annotation_audit,
    status,
    table_year_coverage,
    upload,
)
