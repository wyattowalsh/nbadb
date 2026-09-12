from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer

from nbadb.cli.app import app

# src/nbadb/cli/commands/chat.py → parents[4] = project root
CHAT_APP = Path(__file__).resolve().parents[4] / "chat"
REPO_ROOT = Path(__file__).resolve().parents[4]


@app.command()
def chat(
    port: int = typer.Option(8421, "--port", "-p", help="Port to serve on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
) -> None:
    """Launch the read-only nbadb catalog Q&A chat UI (Chainlit)."""
    chat_dir = CHAT_APP.resolve()
    app_file = chat_dir / "chainlit_app.py"
    pyproject_file = chat_dir / "pyproject.toml"
    missing = [path.name for path in (app_file, pyproject_file) if not path.exists()]
    if missing:
        typer.echo(
            "Error: canonical chat launcher is unavailable at "
            f"{chat_dir} (missing: {', '.join(missing)})"
        )
        raise typer.Exit(1)

    uv = shutil.which("uv")
    if not uv:
        typer.echo("Error: uv is required but not found on PATH")
        raise typer.Exit(1)

    from nbadb.chat.runtime.core import WarehouseUnavailableError, require_usable_warehouse
    from nbadb.core.config import get_settings

    settings = get_settings()
    env = os.environ.copy()
    # Resolve warehouse from the process that knows repo-relative settings,
    # then pin absolute paths so Chainlit's cwd=chat/ cannot mis-resolve them.
    data_dir = Path(settings.data_dir)
    if not data_dir.is_absolute():
        data_dir = (REPO_ROOT / data_dir).resolve()
    else:
        data_dir = data_dir.resolve()
    duckdb_path = settings.duckdb_path
    if duckdb_path is None:
        duckdb_path = data_dir / "nba.duckdb"
    else:
        duckdb_path = Path(duckdb_path)
        if not duckdb_path.is_absolute():
            duckdb_path = (REPO_ROOT / duckdb_path).resolve()
        else:
            duckdb_path = duckdb_path.resolve()
    try:
        duckdb_path = require_usable_warehouse(duckdb_path)
    except WarehouseUnavailableError as exc:
        typer.echo(
            f"Error: {exc}\n"
            "Set NBADB_DUCKDB_PATH to an existing DuckDB file, or build/download data first."
        )
        raise typer.Exit(1) from None
    env["NBADB_DATA_DIR"] = str(data_dir)
    env["NBADB_DUCKDB_PATH"] = str(duckdb_path)

    typer.echo(f"Starting nbadb chat on http://{host}:{port}")
    typer.echo(f"Warehouse: {duckdb_path}")
    try:
        subprocess.run(
            [
                uv,
                "run",
                "chainlit",
                "run",
                str(app_file),
                "--host",
                host,
                "--port",
                str(port),
            ],
            check=True,
            cwd=str(chat_dir),
            env=env,
        )
    except KeyboardInterrupt:
        typer.echo("\nChat server stopped.")
