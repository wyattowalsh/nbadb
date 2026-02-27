from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

DataDirOption = Annotated[
    Path | None,
    typer.Option("--data-dir", "-d", help="Data output directory"),
]
FormatOption = Annotated[
    list[str] | None,
    typer.Option("--format", "-f", help="Output formats"),
]
VerboseOption = Annotated[
    bool,
    typer.Option("--verbose", "-v", help="Enable debug logging"),
]
SeasonOption = Annotated[
    str | None,
    typer.Option("--season", "-s", help="Season year (e.g. 2024-25)"),
]
