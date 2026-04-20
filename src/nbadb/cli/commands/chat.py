from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from nbadb.cli.app import app

# src/nbadb/cli/commands/chat.py → parents[4] = project root
CHAT_APP = Path(__file__).resolve().parents[4] / "apps" / "chat"


@app.command()
def chat(
    port: int = typer.Option(8421, "--port", "-p", help="Port to serve on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
) -> None:
    """Launch the AI-powered NBA data analytics chat UI."""
    chat_dir = CHAT_APP.resolve()
    app_file = chat_dir / "chainlit_app.py"
    if not app_file.exists():
        typer.echo(f"Error: chat app not found at {app_file}")
        raise typer.Exit(1)

    uv = shutil.which("uv")
    if not uv:
        typer.echo("Error: uv is required but not found on PATH")
        raise typer.Exit(1)

    typer.echo(f"Starting nbadb chat on http://{host}:{port}")
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
        )
    except KeyboardInterrupt:
        typer.echo("\nChat server stopped.")
